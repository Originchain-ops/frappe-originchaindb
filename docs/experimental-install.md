# Experimental backend installation

This branch contains an implementation, not verified OriginChainDB support. The
headless application CI uses ordinary PostgreSQL 18. The real engine may reject
isolation, catalog, DDL or query operations; those failures must remain visible.

Use a fresh development Bench with Python 3.14 and the exact pinned application
revisions from the README. Do not apply this to an existing production site.

## Install the adapter and patches

From this repository, with paths adjusted to your Bench:

```sh
../frappe-bench/env/bin/pip install ".[backend]"
python integration/apply.py frappe ../frappe-bench/apps/frappe
python integration/apply.py erpnext ../frappe-bench/apps/erpnext
```

Patch application verifies each clean Git checkout and exact commit before writing.
It refuses dirty checkouts and moved versions. Keep the package installed in the
same Python environment as Frappe; the patch imports it at backend selection time.

## Provision the target explicitly

Use a dedicated disposable database and an existing empty schema exclusively
assigned to this site. Obtain the PostgreSQL listener and SQL credentials from the
instance's Connect panel. The adapter does not create or grant database users,
create/drop databases, or remove partial state after failure.

Create a private connection JSON file outside your repository:

```json
{
  "db_backend": "originchaindb",
  "db_type": "postgres",
  "originchaindb_experimental": true,
  "db_host": "YOUR_SQL_LISTENER",
  "db_port": 5432,
  "db_name": "YOUR_DISPOSABLE_DATABASE",
  "db_user": "YOUR_SQL_IDENTITY",
  "db_password": "YOUR_SQL_PASSWORD",
  "db_schema": "public",
  "db_sslmode": "verify-full",
  "db_sslrootcert": "/absolute/path/to/instance-ca.pem"
}
```

Replace the example port with the actual port. Omit `db_sslrootcert` only when the
listener uses the driver's configured trust store. Restrict access to this file;
Frappe copies the connection configuration into its usual site configuration.
Unset ambient libpq settings such as `PGSERVICE`, `PGHOSTADDR` and `PGOPTIONS`.

From the Bench directory:

```sh
bench new-originchaindb-site oc-dev.local --connection-config /private/oc-connection.json
bench --site oc-dev.local install-app erpnext
```

The first command prompts for the new Administrator password. For CI only, supply
`OC_ADMIN_PASSWORD` securely through the environment. There is no `--force` mode.
If creation fails, inspect the error and partially initialized schema; use a new
empty database/schema for the next clean attempt. Schema changes are not assumed
to roll back. An unsupported repeatable-read transaction is a blocker, not a reason
to downgrade isolation.

## What the code currently does

- Routes database creation and runtime connections through `OriginChainDatabase`.
- Uses PostgreSQL driver binding, Frappe type/schema mapping, ORM and transaction methods.
- Checks backend opt-in, listener details, TLS and transaction isolation.
- Bootstraps the pinned core SQL over the driver, omitting destructive DROP statements.
- Prevents DDL from silently committing pending application writes.
- Splits schema-only batches while rejecting mixed/parameterized SQL batches.
- Makes the Lost Opportunity and Pick List aggregation paths choose the PostgreSQL dialect.

The inherited PostgreSQL schema/catalog and raw query surface still needs engine
validation. Native CLI database commands, dump/restore, reinstall and managed
database/user deletion are not supported. Full upstream suites, UI behavior,
accounting, inventory, concurrency and operational recovery remain release gates.
Do not interpret installation or smoke-test success as full functionality.

For the reference CI only, a localhost configuration may set
`originchaindb_reference_postgres: true` and `db_sslmode: disable`. Reports identify
that target as reference PostgreSQL; this option does not emulate OriginChainDB.
