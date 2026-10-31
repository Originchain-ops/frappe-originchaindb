"""Small behavioral prerequisites for the PostgreSQL-wire integration candidate.

Only generated tables are mutated. Passing these checks cannot certify Frappe,
ERPNext, the MySQL surface, or a different engine build/topology.
"""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from .config import TestConfig


class ProbeFailure(Exception):
    """A fixed diagnostic written by this module, without server/credential text."""


def require(condition: bool, message: str):
    if not condition:
        raise ProbeFailure(message)


def safe_error(error: Exception) -> dict:
    code = getattr(error, "pgcode", None)
    return {
        "error_type": type(error).__name__,
        "sqlstate": code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code) else None,
        "detail": str(error) if isinstance(error, ProbeFailure) else "Driver error; server message withheld.",
    }


def quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class Scratch:
    def __init__(self, config: TestConfig, connect):
        self.config = config
        self.connect = connect
        self.connections = []
        prefix = "tabOC Probe " + uuid.uuid4().hex
        self.names = [prefix + " Parent", prefix + " Child"]
        self.tables = [quoted(config.schema) + "." + quoted(name) for name in self.names]
        self.created = []
        self.creation_attempted = []

    def connection(self, isolation="READ COMMITTED"):
        conn = self.connect(**self.config.connection_kwargs())
        self.connections.append(conn)
        conn.set_session(isolation_level=isolation, autocommit=False)
        with conn.cursor() as cursor:
            # Refuse to continue if the server cannot bound a faulty lock probe.
            cursor.execute("SET statement_timeout = 5000")
            cursor.execute("SET lock_timeout = 2000")
            cursor.execute("SET search_path TO %s", (self.config.schema,))
        conn.commit()
        return conn

    def setup(self):
        conn = self.connection()
        with conn.cursor() as cursor:
            for table in self.tables:
                self.creation_attempted.append(table)
                cursor.execute(
                    f"CREATE TABLE {table} (name VARCHAR(140) PRIMARY KEY, "
                    "amount NUMERIC(21,9), note TEXT DEFAULT 'default-note')"
                )
                conn.commit()
                self.created.append(table)

    def seed(self, value=Decimal("1")):
        conn = self.connection()
        with conn.cursor() as cursor:
            cursor.execute(f"INSERT INTO {self.tables[0]} (name, amount) VALUES (%s, %s)", ("seed", value))
        conn.commit()

    def cleanup(self):
        errors = []
        # Release every open transaction/lock before dropping our own tables.
        for conn in self.connections:
            try:
                conn.rollback()
            except Exception as error:
                errors.append(safe_error(error))
            finally:
                try:
                    conn.close()
                except Exception as error:
                    errors.append(safe_error(error))
        if self.created:
            conn = None
            try:
                conn = self.connect(**self.config.connection_kwargs())
                conn.autocommit = True
                with conn.cursor() as cursor:
                    cursor.execute("SET statement_timeout = 5000")
                    cursor.execute("SET lock_timeout = 2000")
                    for table in reversed(self.created):
                        # No CASCADE and no caller-selected objects.
                        cursor.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception as error:
                errors.append(safe_error(error))
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception as error:
                        errors.append(safe_error(error))
        # An interrupted CREATE/COMMIT can leave an object whose ownership is
        # uncertain. Do not drop it automatically; report it for inspection.
        uncertain = [table for table in self.creation_attempted if table not in self.created]
        return {"ok": not errors and not uncertain, "errors": errors, "uncertain_tables": uncertain}


def transactions(scratch):
    writer, reader = scratch.connection(), scratch.connection()
    with writer.cursor() as w, reader.cursor() as r:
        for table in scratch.tables:
            w.execute(f"INSERT INTO {table} (name, amount) VALUES (%s, %s)", ("tx", Decimal("2.5")))
            w.execute(f"SELECT amount FROM {table} WHERE name = %s", ("tx",))
            require(w.fetchone()[0] == Decimal("2.5"), "Transaction did not read its own write")
            r.execute(f"SELECT COUNT(*) FROM {table}")
            require(r.fetchone()[0] == 0, "Uncommitted write visible to another session")
        writer.rollback()
        reader.rollback()
        for table in scratch.tables:
            r.execute(f"SELECT COUNT(*) FROM {table}")
            require(r.fetchone()[0] == 0, "Rollback left data behind")
            w.execute(f"INSERT INTO {table} (name, amount) VALUES (%s, %s)", ("tx", Decimal("3.5")))
        writer.commit()
        reader.rollback()
        for table in scratch.tables:
            r.execute(f"SELECT amount FROM {table} WHERE name = %s", ("tx",))
            require(r.fetchone()[0] == Decimal("3.5"), "Committed data missing from a second session")


def savepoints(scratch):
    conn = scratch.connection()
    table = scratch.tables[0]
    with conn.cursor() as cursor:
        cursor.execute(f"INSERT INTO {table} (name) VALUES (%s)", ("before",))
        cursor.execute("SAVEPOINT oc_partial")
        cursor.execute(f"INSERT INTO {table} (name) VALUES (%s)", ("after",))
        try:
            cursor.execute(f"INSERT INTO {table} (name) VALUES (%s)", ("before",))
        except Exception as error:
            require(getattr(error, "pgcode", None) == "23505", "Duplicate key did not return SQLSTATE 23505")
        else:
            raise ProbeFailure("Duplicate primary key was accepted")
        cursor.execute("ROLLBACK TO SAVEPOINT oc_partial")
        cursor.execute("RELEASE SAVEPOINT oc_partial")
        cursor.execute(f"SELECT name FROM {table} ORDER BY name")
        require(
            cursor.fetchall() == [("before",)], "Savepoint rollback lost prior work or retained later work"
        )
    conn.commit()
    observer = scratch.connection()
    with observer.cursor() as cursor:
        cursor.execute(f"SELECT name FROM {table}")
        require(cursor.fetchall() == [("before",)], "Savepoint recovery was not committed correctly")


def decimal_storage(scratch):
    conn = scratch.connection()
    table = scratch.tables[0]
    values = [Decimal("123456789012.123456789"), Decimal("0.000000001"), Decimal("-0.100000000")]
    with conn.cursor() as cursor:
        for index, value in enumerate(values):
            cursor.execute(f"INSERT INTO {table} (name, amount) VALUES (%s, %s)", (str(index), value))
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT amount FROM {table} ORDER BY name")
        require(
            [row[0] for row in cursor.fetchall()] == values, "NUMERIC(21,9) changed stored decimal values"
        )
        cursor.execute(f"SELECT SUM(amount) FROM {table}")
        require(cursor.fetchone()[0] == sum(values), "Decimal SUM lost precision")
        cursor.execute("SELECT ROUND(CAST(%s AS NUMERIC), 2)", ("1.005",))
        require(cursor.fetchone()[0] == Decimal("1.01"), "Decimal rounding differs from the reference")


def repeatable_read(scratch):
    scratch.seed()
    reader = scratch.connection("REPEATABLE READ")
    writer = scratch.connection()
    table = scratch.tables[0]
    with reader.cursor() as r, writer.cursor() as w:
        r.execute(f"SELECT amount FROM {table} WHERE name = %s", ("seed",))
        require(r.fetchone()[0] == Decimal("1"), "Initial snapshot is incorrect")
        w.execute(f"UPDATE {table} SET amount = %s WHERE name = %s", (Decimal("2"), "seed"))
        writer.commit()
        r.execute(f"SELECT amount FROM {table} WHERE name = %s", ("seed",))
        require(r.fetchone()[0] == Decimal("1"), "Repeatable read silently behaved as read committed")
        reader.rollback()
        r.execute(f"SELECT amount FROM {table} WHERE name = %s", ("seed",))
        require(r.fetchone()[0] == Decimal("2"), "A new transaction did not see the committed update")


def row_locking(scratch):
    scratch.seed()
    first, second = scratch.connection(), scratch.connection()
    table = scratch.tables[0]
    with first.cursor() as a, second.cursor() as b:
        # A lock_timeout error is also 55P03. Disable it here so a server that
        # ignores NOWAIT fails via statement_timeout (57014), rather than passes.
        b.execute("SET LOCAL lock_timeout = 0")
        a.execute(f"SELECT amount FROM {table} WHERE name = %s FOR UPDATE", ("seed",))
        require(a.fetchone()[0] == Decimal("1"), "Could not lock the fixture row")
        try:
            b.execute(f"SELECT amount FROM {table} WHERE name = %s FOR UPDATE NOWAIT", ("seed",))
        except Exception as error:
            require(getattr(error, "pgcode", None) == "55P03", "Lock conflict did not return SQLSTATE 55P03")
        else:
            raise ProbeFailure("Two sessions acquired an exclusive row lock simultaneously")
        second.rollback()
        first.commit()
        b.execute(f"SELECT amount FROM {table} WHERE name = %s FOR UPDATE NOWAIT", ("seed",))
        require(b.fetchone()[0] == Decimal("1"), "Row lock was not released on commit")


def schema_and_catalog(scratch):
    conn = scratch.connection()
    table = scratch.tables[0]
    index = "oc_probe_index_" + uuid.uuid4().hex
    with conn.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN custom_flag INTEGER DEFAULT 0")
        conn.commit()
        cursor.execute(f"CREATE UNIQUE INDEX {quoted(index)} ON {table} (note)")
        conn.commit()
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (scratch.config.schema, scratch.names[0]),
        )
        require(
            "custom_flag" in {row[0] for row in cursor.fetchall()}, "Added column is missing from catalog"
        )
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = %s",
            (scratch.config.schema, scratch.names[0]),
        )
        require(index in {row[0] for row in cursor.fetchall()}, "Created index is missing from pg_indexes")
        cursor.execute(f"INSERT INTO {table} (name, note) VALUES (%s, %s)", ("one", "unique-note"))
        conn.commit()
        try:
            cursor.execute(f"INSERT INTO {table} (name, note) VALUES (%s, %s)", ("two", "unique-note"))
        except Exception as error:
            require(getattr(error, "pgcode", None) == "23505", "Unique index did not return SQLSTATE 23505")
            conn.rollback()
        else:
            raise ProbeFailure("Unique index did not enforce uniqueness")


def joins_and_aggregation(scratch):
    conn = scratch.connection()
    parent, child = scratch.tables
    with conn.cursor() as cursor:
        cursor.execute(f"INSERT INTO {parent} (name, amount) VALUES (%s, %s)", ("parent", Decimal("4")))
        for name, amount in [("child-a", Decimal("2")), ("child-b", Decimal("3"))]:
            cursor.execute(
                f"INSERT INTO {child} (name, amount, note) VALUES (%s, %s, %s)", (name, amount, "parent")
            )
        cursor.execute(
            f"SELECT p.name, SUM(c.amount), STRING_AGG(c.name, ',' ORDER BY c.name) "
            f"FROM {parent} p LEFT JOIN {child} c ON c.note = p.name GROUP BY p.name"
        )
        require(
            cursor.fetchall() == [("parent", Decimal("5"), "child-a,child-b")],
            "Join/aggregate result differs",
        )


def upsert_and_nulls(scratch):
    conn = scratch.connection()
    table = scratch.tables[0]
    with conn.cursor() as cursor:
        cursor.execute(f"INSERT INTO {table} (name, amount) VALUES (%s, %s)", ("row", Decimal("1")))
        cursor.execute(
            f"INSERT INTO {table} (name, amount) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET amount = EXCLUDED.amount RETURNING amount, note",
            ("row", Decimal("2")),
        )
        require(
            cursor.fetchone() == (Decimal("2"), "default-note"),
            "Upsert lost a default or returned wrong data",
        )
        cursor.execute(f"UPDATE {table} SET note = NULL WHERE name = %s", ("row",))
        cursor.execute(f"SELECT note FROM {table} WHERE name = %s", ("row",))
        require(cursor.fetchone() == (None,), "UPDATE NULL substituted the column default")
    conn.commit()


PROBES = [
    ("transaction_visibility_commit_rollback", transactions),
    ("savepoint_error_recovery", savepoints),
    ("decimal_storage_and_arithmetic", decimal_storage),
    ("repeatable_read_snapshot", repeatable_read),
    ("exclusive_row_lock_nowait", row_locking),
    ("schema_evolution_catalog_unique_index", schema_and_catalog),
    ("joins_and_aggregation", joins_and_aggregation),
    ("upsert_and_nulls", upsert_and_nulls),
]


def run_probes(config: TestConfig, *, allow_scratch_writes=False, connect=None):
    if not allow_scratch_writes:
        raise ValueError(
            "Probes create temporary-use tables: pass --allow-scratch-writes for a disposable database"
        )
    if connect is None:
        import psycopg2

        connect = psycopg2.connect
    results = []
    for name, probe in PROBES:
        scratch = Scratch(config, connect)
        result = {"id": name, "status": "failed", "scratch_tables": scratch.tables}
        try:
            scratch.setup()
            probe(scratch)
            result["status"] = "passed"
        except Exception as error:
            result.update(safe_error(error))
        finally:
            result["cleanup"] = scratch.cleanup()
        if not result["cleanup"]["ok"]:
            result["status"] = "failed"
        results.append(result)
    return {
        "report_kind": "postgresql_wire_prerequisites",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_label": "reference_postgresql"
        if config.reference_postgres
        else "operator_supplied_originchaindb",
        "server_identity_verified": False,
        "all_prerequisites_passed": all(result["status"] == "passed" for result in results),
        "adapter_exercised_by_these_probes": False,
        "frappe_erpnext_tested": False,
        "release_ready": False,
        "scope": "Eight prerequisites only. Does not validate a complete application or database product identity.",
        "results": results,
    }
