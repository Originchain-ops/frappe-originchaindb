"""Real Frappe database subclass; PostgreSQL dialect, OriginChainDB identity.

All unoverridden ORM, type, schema, error and transaction operations are inherited
from the pinned Frappe PostgreSQL implementation. Their engine compatibility is
experimental and must be established on the actual deployment.
"""

import frappe
import psycopg2
import sqlparse
from frappe.database.database import Database
from frappe.database.postgres.database import PostgresDatabase
from frappe.database.utils import EmptyQueryValues
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

from .config import connection_settings, validate
from .sql import partial_rollback, transaction_kind


class OriginChainDatabase(PostgresDatabase):
    backend_name = "originchaindb"

    def __init__(self, socket=None, host=None, user=None, password=None, port=None, cur_db_name=None):
        conf = frappe.conf
        validate(conf)
        supplied = {
            "db_host": host,
            "db_user": user,
            "db_password": password,
            "db_port": port,
            "db_name": cur_db_name,
        }
        if socket or any(value is not None and value != conf[key] for key, value in supplied.items()):
            raise ValueError(
                "Alternate database/credential/replica routing is not implemented for OriginChainDB"
            )
        super().__init__(None, conf.db_host, conf.db_user, conf.db_password, conf.db_port, conf.db_name)

    def get_connection(self):
        conn = psycopg2.connect(**connection_settings(frappe.conf))
        try:
            conn.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)
            with conn.cursor() as cursor:
                # Force the driver to start a transaction at the requested level.
                # An unsupported level must fail here, before any application write.
                cursor.execute("SELECT 1")
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone() != ("repeatable read",):
                    raise RuntimeError("The listener did not establish repeatable-read isolation")
            conn.rollback()
            return conn
        except BaseException:
            conn.close()
            raise

    def check_implicit_commit(self, query, query_type):
        # OriginChainDB DDL is not transactional. Restore the base guard that the
        # stock PostgreSQL backend disables, rather than silently committing DML.
        Database.check_implicit_commit(self, query, query_type)

    def check_transaction_status(self, query, query_type=None):
        prior_writes = self.transaction_writes
        kind = transaction_kind(query)
        super().check_transaction_status(query, kind)
        if kind == "rollback" and partial_rollback(query):
            # Rollback to a savepoint does not discard earlier writes. A conservative
            # count prevents subsequent DDL from implicitly committing that work.
            self.transaction_writes = prior_writes

    def begin(self, *, read_only=False):
        mode = " READ ONLY" if read_only or frappe.flags.read_only else ""
        self.sql("START TRANSACTION ISOLATION LEVEL REPEATABLE READ" + mode)

    def updatedb(self, doctype, meta=None):
        if self._disable_transaction_control:
            raise RuntimeError("Schema synchronization requires an explicit commit boundary")
        previous = getattr(self, "_originchain_schema_sync", False)
        self.commit()
        self._originchain_schema_sync = True
        try:
            return super().updatedb(doctype, meta)
        finally:
            self._originchain_schema_sync = previous

    def sql(self, query, values=EmptyQueryValues, *args, **kwargs):
        statements = sqlparse.split(str(query))
        if len(statements) <= 1:
            if getattr(self, "_originchain_schema_sync", False) and transaction_kind(str(query)) in {
                "create",
                "alter",
                "drop",
                "truncate",
                "rename",
            }:
                # This is an explicit DocType schema operation, mirroring MariaDB's
                # DDL boundaries. Never enable it for ordinary document writes.
                self.commit()
            return super().sql(query, values, *args, **kwargs)
        if values is not EmptyQueryValues and values is not None:
            raise ValueError("Parameterized multi-statement SQL is not supported by the experimental backend")
        # Upstream schema synchronization emits batches of DDL. Execute each
        # statement separately; reject mixed DML/control batches before execution.
        for statement in statements:
            kind = sqlparse.parse(statement)[0].get_type()
            if kind not in {"CREATE", "ALTER", "DROP"}:
                raise ValueError("Only schema-only SQL batches are supported by the experimental backend")
        if self.transaction_writes and not getattr(self, "_originchain_schema_sync", False):
            raise frappe.ImplicitCommitError("Commit pending data writes before schema changes")
        result = None
        for statement in statements:
            result = self.sql(statement, EmptyQueryValues, *args, **kwargs)
        return result
