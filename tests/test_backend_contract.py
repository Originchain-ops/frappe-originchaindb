import unittest
from unittest.mock import Mock, patch

from frappe_originchaindb.config import connection_settings, validate
from frappe_originchaindb.setup import assert_empty_schema, bootstrap_statements, drop_user_and_database
from frappe_originchaindb.sql import partial_rollback, transaction_kind


class TransactionClassificationTests(unittest.TestCase):
    def test_comments_do_not_hide_writes_or_schema_changes(self):
        self.assertEqual(transaction_kind("-- audit\nUPDATE x SET a=1"), "update")
        self.assertEqual(transaction_kind("/* comment */ CREATE TABLE x (a INT)"), "create")

    def test_writable_cte_counts_as_a_write(self):
        self.assertEqual(
            transaction_kind("WITH changed AS (UPDATE x SET a=1 RETURNING a) SELECT * FROM changed"), "update"
        )

    def test_literals_and_read_only_ctes_do_not_become_writes(self):
        self.assertEqual(transaction_kind("SELECT 'UPDATE x SET a=1'"), "select")
        self.assertEqual(transaction_kind("WITH x AS (SELECT 1) SELECT * FROM x"), "with")

    def test_partial_and_full_rollback_are_distinguished(self):
        self.assertTrue(partial_rollback("/* comment */ ROLLBACK TO SAVEPOINT first"))
        self.assertTrue(partial_rollback("ROLLBACK WORK TO first"))
        self.assertFalse(partial_rollback("ROLLBACK AND CHAIN"))
        self.assertFalse(partial_rollback("SELECT 'ROLLBACK TO first'"))


def configuration():
    return {
        "db_backend": "originchaindb",
        "db_type": "postgres",
        "originchaindb_experimental": True,
        "db_host": "db.example.invalid",
        "db_port": 5432,
        "db_name": "test",
        "db_user": "test",
        "db_password": "unit-test-only",
    }


class BackendConfigurationTests(unittest.TestCase):
    def test_explicit_engine_and_opt_in_required(self):
        for changes in [
            {"db_backend": "other"},
            {"db_type": "mariadb"},
            {"originchaindb_experimental": False},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate({**configuration(), **changes}, environment={})

    def test_remote_plaintext_and_isolation_downgrade_refused(self):
        for changes in [
            {"db_sslmode": "disable"},
            {"db_isolation_level": "read committed"},
            {"originchaindb_reference_postgres": True},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate({**configuration(), **changes}, environment={})

    def test_listener_must_be_explicit_and_schema_safe(self):
        for changes in [
            {"db_port": None},
            {"db_port": True},
            {"db_schema": "public; DROP SCHEMA public"},
            {"db_socket": "/tmp/socket"},
            {"db_password": ""},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate({**configuration(), **changes}, environment={})

    def test_tls_and_repeatable_read_are_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = connection_settings(configuration())
        self.assertEqual(settings["sslmode"], "verify-full")
        self.assertEqual(settings["dbname"], "test")

    def test_ambient_service_cannot_override_listener(self):
        with self.assertRaisesRegex(ValueError, "ambient"):
            validate(configuration(), environment={"PGSERVICE": "production"})


class ManagedSchemaTests(unittest.TestCase):
    def test_no_drop_statements_are_executed_from_bootstrap(self):
        statements = bootstrap_statements(
            '-- Header\nDROP TABLE IF EXISTS "tabDocType"; CREATE TABLE "tabDocType" (name TEXT);'
        )
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE TABLE"))

    def test_bootstrap_rejects_unexpected_sql_before_execution(self):
        for sql in ["INSERT INTO x VALUES (1);", "DROP SCHEMA public;", "COPY x FROM STDIN;", ""]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                bootstrap_statements(sql)

    def test_bootstrap_preserves_semicolons_inside_literals(self):
        statements = bootstrap_statements("CREATE TABLE x (a TEXT DEFAULT 'a;b'); CREATE INDEX ON x(a);")
        self.assertEqual(len(statements), 2)
        self.assertIn("'a;b'", statements[0])

    def test_nonempty_or_missing_schema_refused(self):
        for replies in [[], [("public",)]]:
            db = Mock(db_schema="public")
            db.sql.side_effect = [replies, [(1,)], [(0,)], [(0,)]]
            with self.assertRaises(ValueError):
                assert_empty_schema(db)

    def test_sequences_alone_make_schema_nonempty(self):
        db = Mock(db_schema="public")
        db.sql.side_effect = [[("public",)], [(0,)], [(1,)]]
        with self.assertRaises(ValueError):
            assert_empty_schema(db)

    def test_database_drop_is_never_emulated(self):
        with self.assertRaisesRegex(RuntimeError, "no objects were deleted"):
            drop_user_and_database("test", "test")
