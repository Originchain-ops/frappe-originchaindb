"""Reproducible, bounded source inspection; source hits are not runtime results."""

import subprocess
from pathlib import Path

BASELINES = {
    "frappe": {"tag": "v16.54.0", "commit": "2fcb9397a1f1da353b21e53d2f97ec56653acd02"},
    "erpnext": {"tag": "v16.53.0", "commit": "9cd11b19575bfc34f092a24f6c8b368c4dd69481"},
}

# Literal anchors deliberately fail if upstream moves or removes the evidence.
CHECKS = [
    {
        "id": "mysql_schema_inspection",
        "project": "frappe",
        "path": "frappe/database/mariadb/mysqlclient.py",
        "anchor": "SHOW INDEX FROM",
        "surface": "mysql",
        "assessment": "documented_incompatibility",
        "reason": "The MySQL adapter rejects SHOW statements required by this backend.",
        "documentation": "https://originchaindb.com/docs/compatibility/mysql-wire",
    },
    {
        "id": "mysql_customer_naming",
        "project": "erpnext",
        "path": "erpnext/selling/doctype/customer/customer.py",
        "anchor": "MAX(CAST(SUBSTRING_INDEX(name, ' ', -1) AS UNSIGNED))",
        "surface": "mysql",
        "assessment": "documented_incompatibility",
        "reason": "The MySQL branch uses SUBSTRING_INDEX; a separate PostgreSQL branch already exists.",
        "documentation": "https://originchaindb.com/docs/compatibility/mysql-wire",
    },
    {
        "id": "mysql_report_aggregation",
        "project": "erpnext",
        "path": "erpnext/crm/report/lost_opportunity/lost_opportunity.py",
        "anchor": "GROUP_CONCAT(OpportunityLostReasonDetail.lost_reason",
        "surface": "mysql; inspect PostgreSQL portability separately",
        "assessment": "documented_incompatibility",
        "reason": "This report directly uses GROUP_CONCAT, which the MySQL adapter rejects.",
        "documentation": "https://originchaindb.com/docs/compatibility/mysql-wire",
    },
    {
        "id": "repeatable_read",
        "project": "frappe",
        "path": "frappe/database/postgres/database.py",
        "anchor": "conn.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)",
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Frappe requests repeatable read; the wire guide establishes read committed as baseline.",
        "documentation": "https://originchaindb.com/docs/connect-sql-client",
    },
    {
        "id": "savepoint_rollback",
        "project": "frappe",
        "path": "frappe/database/database.py",
        "anchor": 'self.sql(f"rollback to savepoint {save_point}")',
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Test partial rollback and recovery after an error inside an active transaction.",
        "documentation": "https://originchaindb.com/docs/postgresql-compatibility",
    },
    {
        "id": "naming_series_locking",
        "project": "frappe",
        "path": "frappe/model/naming.py",
        "anchor": '.where(series.name == key).for_update().select("current")',
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Number allocation depends on locking; successful SELECT syntax alone is insufficient.",
        "documentation": "https://originchaindb.com/docs/transactions",
    },
    {
        "id": "currency_storage",
        "project": "frappe",
        "path": "frappe/database/postgres/database.py",
        "anchor": '"Currency": ("decimal", "21,9")',
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Verify precision, scale, aggregation and application rounding; numeric parity is unestablished.",
        "documentation": "https://originchaindb.com/docs/postgresql-compatibility",
    },
    {
        "id": "site_provisioning",
        "project": "frappe",
        "path": "frappe/database/postgres/setup_db.py",
        "anchor": 'CREATE DATABASE "{frappe.conf.db_name}"',
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Provisioning assumes database administration; a managed-instance bootstrap path needs design.",
        "documentation": "https://originchaindb.com/docs/connect-sql-client",
    },
    {
        "id": "backup_restore",
        "project": "frappe",
        "path": "frappe/database/__init__.py",
        "anchor": 'which("pg_dump")',
        "surface": "postgresql",
        "assessment": "requires_live_validation",
        "reason": "Wire compatibility does not establish pg_dump or restore compatibility.",
        "documentation": "https://originchaindb.com/docs/connect-sql-client",
    },
]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30
    )
    return result.stdout.strip()


def inspect_sources(roots: dict[str, Path]) -> dict:
    sources = {}
    for name, baseline in BASELINES.items():
        root = roots[name].resolve()
        commit = _git(root, "rev-parse", "HEAD")
        clean = not bool(_git(root, "status", "--porcelain", "--untracked-files=all"))
        sources[name] = {**baseline, "observed_commit": commit, "clean": clean}
    findings = []
    for check in CHECKS:
        path = roots[check["project"]] / check["path"]
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        hits = [index for index, line in enumerate(lines, 1) if check["anchor"] in line]
        commit = sources[check["project"]]["observed_commit"]
        findings.append(
            {
                **check,
                "evidence_found": bool(hits),
                "line_numbers": hits,
                "source_url": (
                    f"https://github.com/frappe/{check['project']}/blob/{commit}/{check['path']}"
                    + (f"#L{hits[0]}" if hits else "")
                ),
            }
        )
    baseline_verified = all(
        source["commit"] == source["observed_commit"] and source["clean"] for source in sources.values()
    )
    complete = baseline_verified and all(finding["evidence_found"] for finding in findings)
    return {
        "report_kind": "static_source_audit",
        "docs_review_date": "2026-10-31",
        "baseline_verified": baseline_verified,
        "audit_complete": complete,
        "originchaindb_tested": False,
        "adapter_implemented": False,
        "release_ready": False,
        "scope": "Curated evidence only; not a complete query inventory or a functionality certification.",
        "sources": sources,
        "findings": findings,
    }
