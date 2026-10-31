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

from .config import connection_settings


class OriginChainDatabase(PostgresDatabase):
    backend_name = "originchaindb"

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

    def sql(self, query, values=EmptyQueryValues, *args, **kwargs):
        statements = sqlparse.split(str(query))
        if len(statements) <= 1:
            return super().sql(query, values, *args, **kwargs)
        if values is not EmptyQueryValues and values is not None:
            raise ValueError("Parameterized multi-statement SQL is not supported by the experimental backend")
        # Upstream schema synchronization emits batches of DDL. Execute each
        # statement separately; reject mixed DML/control batches before execution.
        for statement in statements:
            kind = sqlparse.parse(statement)[0].get_type()
            if kind not in {"CREATE", "ALTER", "DROP"}:
                raise ValueError("Only schema-only SQL batches are supported by the experimental backend")
        if self.transaction_writes:
            raise frappe.ImplicitCommitError("Commit pending data writes before schema changes")
        result = None
        for statement in statements:
            result = super().sql(statement, *args, **kwargs)
        return result
