"""Use only explicit test connection settings, never ambient libpq credentials."""

import re
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class TestConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    sslmode: str = "verify-full"
    sslrootcert: str | None = None
    schema: str = "public"
    reference_postgres: bool = False

    @classmethod
    def from_environment(cls, env: Mapping[str, str], *, reference_postgres: bool = False):
        required = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
        missing = ["OC_TEST_" + key for key in required if not env.get("OC_TEST_" + key)]
        if missing:
            raise ValueError("Missing test configuration: " + ", ".join(missing))
        try:
            port = int(env["OC_TEST_PGPORT"])
        except ValueError:
            raise ValueError("OC_TEST_PGPORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise ValueError("OC_TEST_PGPORT must be between 1 and 65535")
        host = env["OC_TEST_PGHOST"]
        mode = env.get("OC_TEST_PGSSLMODE", "verify-full")
        if mode != "verify-full" and not (
            reference_postgres and mode == "disable" and host in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Use verify-full TLS; disable is only allowed for a local reference PostgreSQL")
        if reference_postgres and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Reference PostgreSQL mode is restricted to localhost")
        schema = env.get("OC_TEST_SCHEMA", "public")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("OC_TEST_SCHEMA must be a simple SQL identifier")
        return cls(
            host=host,
            port=port,
            database=env["OC_TEST_PGDATABASE"],
            user=env["OC_TEST_PGUSER"],
            password=env["OC_TEST_PGPASSWORD"],
            sslmode=mode,
            sslrootcert=env.get("OC_TEST_PGSSLROOTCERT"),
            schema=schema,
            reference_postgres=reference_postgres,
        )

    def connection_kwargs(self):
        result = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            "sslmode": self.sslmode,
            "connect_timeout": 10,
            "application_name": "frappe-originchaindb-compat",
            # Empty settings explicitly override ambient libpq service/options variables.
            "service": "",
            "options": "",
            "sslcert": "",
            "sslkey": "",
            "hostaddr": "",
            "sslrootcert": self.sslrootcert or "",
        }
        return result
