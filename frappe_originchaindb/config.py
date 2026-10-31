"""Explicit backend identity and connection contract, independently testable."""

import os
import re
from pathlib import Path


def validate(config, *, environment=None):
    if config.get("db_backend") != "originchaindb" or config.get("db_type") != "postgres":
        raise ValueError("OriginChainDB requires db_backend=originchaindb and db_type=postgres")
    if config.get("originchaindb_experimental") is not True:
        raise ValueError("Set originchaindb_experimental=true to opt into the experimental backend")
    for key in ("db_host", "db_name", "db_user", "db_password"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"A nonempty {key} is required")
    port = config.get("db_port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("db_port must be an explicit integer between 1 and 65535")
    if config.get("db_socket"):
        raise ValueError("The OriginChainDB backend requires an explicit TCP listener")
    schema = config.get("db_schema", "public")
    if not isinstance(schema, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("db_schema must be a simple SQL identifier")
    reference = config.get("originchaindb_reference_postgres", False)
    if not isinstance(reference, bool):
        raise ValueError("originchaindb_reference_postgres must be a boolean")
    if reference and config["db_host"] not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Reference PostgreSQL mode only permits localhost")
    sslmode = config.get("db_sslmode", "verify-full")
    if sslmode != "verify-full" and not (reference and sslmode == "disable"):
        raise ValueError("Remote connections require db_sslmode=verify-full")
    if cert := config.get("db_sslrootcert"):
        if not isinstance(cert, str) or not Path(cert).is_file():
            raise ValueError("db_sslrootcert must name an existing CA file")
    if config.get("db_isolation_level", "repeatable read").lower() != "repeatable read":
        raise ValueError("This backend preserves Frappe's repeatable-read isolation requirement")
    environment = os.environ if environment is None else environment
    overrides = {"PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"}
    inherited = sorted(
        key for key, value in environment.items() if key.startswith("PG") and value and key not in overrides
    )
    if inherited:
        raise ValueError("Unset ambient libpq settings: " + ", ".join(inherited))


def connection_settings(config):
    validate(config)
    settings = {
        "host": config["db_host"],
        "port": config["db_port"],
        "dbname": config["db_name"],
        "user": config["db_user"],
        "password": config["db_password"],
        "sslmode": config.get("db_sslmode", "verify-full"),
        "connect_timeout": 10,
        "application_name": "frappe-originchaindb-experimental",
    }
    if config.get("db_sslrootcert"):
        settings["sslrootcert"] = config["db_sslrootcert"]
    return settings
