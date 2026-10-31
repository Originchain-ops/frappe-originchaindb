"""Bootstrap an already provisioned, empty managed schema without admin SQL."""

import json
from pathlib import Path

from .config import validate


def assert_empty_schema(db):
    rows = db.sql(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
        (db.db_schema,),
    )
    if not rows:
        raise ValueError("Provision the configured schema before creating the Frappe site")
    # Tables/views, sequences and routines can all belong to another application.
    for catalog in ("tables", "sequences", "routines"):
        field = {"tables": "table_schema", "sequences": "sequence_schema", "routines": "routine_schema"}[
            catalog
        ]
        rows = db.sql(
            f"SELECT COUNT(*) FROM information_schema.{catalog} WHERE {field} = %s", (db.db_schema,)
        )
        if rows[0][0]:
            raise ValueError("OriginChainDB site creation requires an empty, exclusively assigned schema")


def setup_database(force=False, verbose=None, mariadb_user_host_login_scope=None):
    import frappe

    if force:
        raise ValueError("Forced recreation of managed OriginChainDB databases is not supported")
    validate(frappe.conf)
    frappe.connect()
    assert_empty_schema(frappe.db)
    frappe.db.rollback()


def bootstrap_statements(source):
    import sqlparse

    statements = []
    for raw in sqlparse.split(source):
        statement = sqlparse.format(raw, strip_comments=True).strip()
        if not statement:
            continue
        if statement.upper().startswith("DROP TABLE IF EXISTS "):
            continue
        if not statement.upper().startswith(("CREATE TABLE ", "CREATE INDEX ")):
            raise ValueError("Unexpected statement in the pinned Frappe bootstrap SQL")
        statements.append(statement)
    if not statements:
        raise ValueError("No bootstrap statements found")
    return statements


def bootstrap_database(verbose=None, source_sql=None):
    import frappe

    if source_sql:
        raise ValueError("SQL-file restore is not implemented for the OriginChainDB backend")
    frappe.connect()
    assert_empty_schema(frappe.db)
    source = Path(frappe.__file__).parent / "database" / "postgres" / "framework_postgres.sql"
    statements = bootstrap_statements(source.read_text(encoding="utf-8"))
    # Each DDL may apply immediately on the engine. Never claim rollback undoes it.
    for statement in statements:
        frappe.db.sql_ddl(statement)
    frappe.db.commit()


def drop_user_and_database(*args, **kwargs):
    raise RuntimeError(
        "Managed OriginChainDB database/user deletion is not implemented; no objects were deleted"
    )


def create_site(site, connection_config, admin_password=None):
    import frappe
    from frappe.installer import _new_site

    if not site or Path(site).name != site or site in {".", ".."} or "/" in site or "\\" in site:
        raise ValueError("Use a site name without path separators")
    config = json.loads(Path(connection_config).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("The connection configuration must be a JSON object")
    validate(config)
    # No force, arbitrary source SQL, remote admin credentials or destructive
    # rollback callback. On failure retain local state for diagnosis/recovery.
    try:
        _new_site(
            db_name=config["db_name"],
            site=site,
            db_type="postgres",
            db_user=config["db_user"],
            db_password=config["db_password"],
            db_host=config["db_host"],
            db_port=config["db_port"],
            site_config=config,
            admin_password=admin_password,
            setup_db=True,
        )
    finally:
        frappe.destroy()
