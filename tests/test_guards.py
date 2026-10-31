import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from frappe_originchaindb_compat.audit import BASELINES, CHECKS, inspect_sources
from frappe_originchaindb_compat.cli import main
from frappe_originchaindb_compat.config import TestConfig
from frappe_originchaindb_compat.probes import ProbeFailure, Scratch, run_probes, safe_error


def test_environment():
    return {
        "OC_TEST_PGHOST": "test.example.invalid",
        "OC_TEST_PGPORT": "5432",
        "OC_TEST_PGDATABASE": "scratch",
        "OC_TEST_PGUSER": "tester",
        "OC_TEST_PGPASSWORD": "a-secret-that-must-not-appear",
    }


class ConfigurationTests(unittest.TestCase):
    def test_ambient_services_and_connection_options_refused(self):
        for key in ["PGSERVICE", "PGHOSTADDR", "PGOPTIONS", "PGSSLROOTCERT", "PGPASSFILE"]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Unset ambient"):
                TestConfig.from_environment({**test_environment(), key: "unrelated-production-setting"})

    def test_rejects_ambient_production_connection(self):
        with self.assertRaisesRegex(ValueError, "Missing test configuration"):
            TestConfig.from_environment({"PGHOST": "production", "PGPASSWORD": "secret"})

    def test_password_hidden_in_repr(self):
        config = TestConfig.from_environment(test_environment())
        self.assertNotIn(config.password, repr(config))

    def test_remote_tls_cannot_be_downgraded(self):
        for mode in ["disable", "allow", "prefer", "require", "verify-ca"]:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                TestConfig.from_environment({**test_environment(), "OC_TEST_PGSSLMODE": mode})

    def test_remote_reference_target_refused(self):
        with self.assertRaises(ValueError):
            TestConfig.from_environment(test_environment(), reference_postgres=True)

    def test_local_reference_without_tls_is_explicit(self):
        env = {**test_environment(), "OC_TEST_PGHOST": "127.0.0.1", "OC_TEST_PGSSLMODE": "disable"}
        with self.assertRaises(ValueError):
            TestConfig.from_environment(env)
        self.assertTrue(TestConfig.from_environment(env, reference_postgres=True).reference_postgres)

    def test_invalid_port_and_schema_refused(self):
        for patch_env in [
            {"OC_TEST_PGPORT": "0"},
            {"OC_TEST_PGPORT": "abc"},
            {"OC_TEST_SCHEMA": "x;DROP TABLE y"},
        ]:
            with self.subTest(patch_env=patch_env), self.assertRaises(ValueError):
                TestConfig.from_environment({**test_environment(), **patch_env})


class ProbeGuardTests(unittest.TestCase):
    def test_no_connection_without_write_opt_in(self):
        connect = Mock()
        with self.assertRaises(ValueError):
            run_probes(TestConfig.from_environment(test_environment()), connect=connect)
        connect.assert_not_called()

    def test_driver_messages_are_not_reported(self):
        error = RuntimeError("password=a-secret-that-must-not-appear host=private.example")
        self.assertNotIn("a-secret", json.dumps(safe_error(error)))
        self.assertNotIn("private.example", json.dumps(safe_error(error)))

    def test_failed_connections_never_become_passes(self):
        config = TestConfig.from_environment(test_environment())
        report = run_probes(
            config, allow_scratch_writes=True, connect=Mock(side_effect=RuntimeError("secret"))
        )
        self.assertFalse(report["all_prerequisites_passed"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(len(report["results"]), 8)
        self.assertNotIn("secret", json.dumps(report))

    def test_cleanup_runs_after_probe_failure(self):
        fake = Mock()
        fake.tables = ["generated_table"]
        fake.cleanup.return_value = {"ok": True, "errors": [], "uncertain_tables": []}
        with (
            patch("frappe_originchaindb_compat.probes.Scratch", return_value=fake),
            patch(
                "frappe_originchaindb_compat.probes.PROBES",
                [("broken", Mock(side_effect=ProbeFailure("failed check")))],
            ),
        ):
            report = run_probes(
                TestConfig.from_environment(test_environment()), allow_scratch_writes=True, connect=Mock()
            )
        fake.cleanup.assert_called_once()
        self.assertEqual(report["results"][0]["status"], "failed")

    def test_cleanup_failure_invalidates_success(self):
        fake = Mock()
        fake.tables = ["generated_table"]
        fake.cleanup.return_value = {"ok": False, "errors": [], "uncertain_tables": ["generated_table"]}
        with (
            patch("frappe_originchaindb_compat.probes.Scratch", return_value=fake),
            patch(
                "frappe_originchaindb_compat.probes.PROBES",
                [("passed_probe", Mock())],
            ),
        ):
            report = run_probes(
                TestConfig.from_environment(test_environment()), allow_scratch_writes=True, connect=Mock()
            )
        self.assertFalse(report["all_prerequisites_passed"])

    def test_even_all_prerequisites_do_not_certify_application(self):
        fake = Mock()
        fake.tables = []
        fake.cleanup.return_value = {"ok": True, "errors": [], "uncertain_tables": []}
        with (
            patch("frappe_originchaindb_compat.probes.Scratch", return_value=fake),
            patch(
                "frappe_originchaindb_compat.probes.PROBES",
                [("passed_probe", Mock())],
            ),
        ):
            report = run_probes(
                TestConfig.from_environment(test_environment()), allow_scratch_writes=True, connect=Mock()
            )
        self.assertTrue(report["all_prerequisites_passed"])
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["frappe_erpnext_tested"])

    def test_uncertain_creation_is_reported_without_dropping_it(self):
        connector = Mock()
        scratch = Scratch(TestConfig.from_environment(test_environment()), connector)
        scratch.creation_attempted = [scratch.tables[0]]
        cleanup = scratch.cleanup()
        self.assertFalse(cleanup["ok"])
        self.assertEqual(cleanup["uncertain_tables"], scratch.creation_attempted)
        connector.assert_not_called()


class AuditTests(unittest.TestCase):
    def make_sources(self, root):
        roots = {name: root / name for name in BASELINES}
        for check in CHECKS:
            path = roots[check["project"]] / check["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(check["anchor"] + "\n")
        return roots

    @staticmethod
    def git_stub(root, *args):
        return BASELINES[root.name]["commit"] if args[0] == "rev-parse" else ""

    def test_missing_evidence_invalidates_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = self.make_sources(Path(temp))
            with patch("frappe_originchaindb_compat.audit._git", side_effect=self.git_stub):
                self.assertTrue(inspect_sources(roots)["audit_complete"])
                (roots["frappe"] / CHECKS[0]["path"]).write_text("", encoding="utf-8")
                report = inspect_sources(roots)
                self.assertFalse(report["audit_complete"])
                self.assertFalse(report["findings"][0]["evidence_found"])

    def test_dirty_source_cannot_be_pinned_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = self.make_sources(Path(temp))

            def dirty_git(root, *args):
                return self.git_stub(root, *args) if args[0] == "rev-parse" else " M changed.py"

            with patch("frappe_originchaindb_compat.audit._git", side_effect=dirty_git):
                self.assertFalse(inspect_sources(roots)["audit_complete"])


class CliTests(unittest.TestCase):
    def test_missing_write_flag_fails_without_importing_driver(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("frappe_originchaindb_compat.cli.run_probes") as run,
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                result = main(["probe", "--output", str(Path(temp) / "report.json")])
            self.assertEqual(result, 3)
            run.assert_not_called()
            self.assertFalse((Path(temp) / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
