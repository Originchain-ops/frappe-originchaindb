# Frappe + ERPNext on OriginChainDB: compatibility workbench

**Status: prerequisite tooling only. No OriginChainDB backend adapter is implemented.**

This project prepares a future Frappe and ERPNext port using OriginChainDB's
PostgreSQL wire interface as the initial candidate. It does **not** install
ERPNext on OriginChainDB, replace MariaDB, or establish application compatibility.
No OriginChainDB instance was accessed for the initial release.

The first prerelease contains a reproducible source audit, eight database behavior
probes, offline guard tests, packaging, and a CI reference run on ordinary PostgreSQL.
Green reference CI proves the probe harness works on that reference database;
it provides no OriginChainDB compatibility evidence.

## Reviewed baseline

| Component | Version | Pinned commit |
| --- | --- | --- |
| Frappe | v16.54.0 | `2fcb9397a1f1da353b21e53d2f97ec56653acd02` |
| ERPNext | v16.53.0 | `9cd11b19575bfc34f092a24f6c8b368c4dd69481` |
| OriginChainDB | Public documentation reviewed 31 October 2026 | No engine build tested |

See [the generated audit](evidence/source-audit.json) for exact source links.
It is a curated inspection, not an exhaustive SQL inventory.

## Why a direct connection swap is insufficient

The [MySQL adapter](https://originchaindb.com/docs/compatibility/mysql-wire) documents
unsupported `SHOW` commands, `GROUP_CONCAT` and `SUBSTRING_INDEX`; the pinned source
contains relevant uses. The MySQL path therefore needs changes.

Frappe's PostgreSQL backend requests repeatable read, while the
[connection guide](https://originchaindb.com/docs/connect-sql-client) identifies
read committed as the wire baseline and says unsupported higher isolation is refused.
The exact deployed behavior must be tested; this project never silently lowers isolation.

The [PostgreSQL compatibility guide](https://originchaindb.com/docs/postgresql-compatibility)
also distinguishes immediate schema changes from transactional writes and leaves
complete numeric precision parity unestablished. Accounting correctness needs both
database checks and ERPNext workflow tests.

## Reproduce the source audit

Python 3.10+ and Git are required. From this repository:

```sh
python -m pip install .
git clone --depth 1 --branch v16.54.0 https://github.com/frappe/frappe.git ../frappe-audit
git clone --depth 1 --branch v16.53.0 https://github.com/frappe/erpnext.git ../erpnext-audit
frappe-originchaindb-compat audit --frappe ../frappe-audit --erpnext ../erpnext-audit --output audit.json
```

The audit checks the commit IDs, a clean working tree, and each expected source anchor.
A moved tag, changed checkout or missing anchor fails the audit. Audit success means
the evidence was reproduced, never that the database port works.

## Run database prerequisites later

Use a **disposable database** with a writable PostgreSQL listener and permission to
create, alter and drop tables. Install `python -m pip install ".[live]"`. Supply these
environment variables from that instance's connection panel and your secret manager:

| Variable | Meaning |
| --- | --- |
| `OC_TEST_PGHOST` | Actual SQL listener host |
| `OC_TEST_PGPORT` | Actual SQL listener port; do not infer it from HTTP |
| `OC_TEST_PGDATABASE` | Disposable test database |
| `OC_TEST_PGUSER` | SQL identity |
| `OC_TEST_PGPASSWORD` | SQL password, supplied securely |
| `OC_TEST_PGSSLMODE` | `verify-full` (default and required for remote tests) |
| `OC_TEST_PGSSLROOTCERT` | Supplied CA file if required |
| `OC_TEST_SCHEMA` | Existing schema, default `public` |

Ordinary `PGHOST`, `PGDATABASE`, `PGUSER` and `PGPASSWORD` are not used as test
configuration. An HTTP bearer is not assumed to be a SQL password.
Unset other `PG*` environment settings such as `PGSERVICE`, `PGHOSTADDR` and
`PGOPTIONS`; the CLI refuses them to prevent an ambient service or address from
altering the explicit test connection.

```sh
frappe-originchaindb-compat probe --allow-scratch-writes --output live-report.json
```

The probes use generated table names starting with `tabOC Probe`, create no users
or databases, and attempt cleanup after every probe. They do not wrap DDL in a
pretend rollback. Cleanup errors and ambiguous object creation are failures, with
affected generated names included for inspection. No `DROP ... CASCADE` is used.

Each connection requires working statement and lock timeouts before probes begin.
The checks cover:

1. Read-your-writes, isolation of uncommitted writes, commit and multi-table rollback.
2. Savepoint recovery after a duplicate-key error.
3. `NUMERIC(21,9)` round trips, summation and one rounding boundary.
4. Repeatable-read behavior across two sessions.
5. Exclusive row locking, `NOWAIT`, and release after commit.
6. Column/index changes, catalog reflection and uniqueness enforcement.
7. Joins and PostgreSQL string aggregation.
8. Upserts, defaults and explicit NULL updates.

Exit codes: `0` means the requested audit/prerequisites passed; `2` means checks
failed; `3` means configuration or execution failed. Every report keeps
`release_ready: false`. These checks neither identify the server product nor
certify Frappe/ERPNext. Driver error messages are withheld to avoid recording
connection details; SQLSTATE and fixed diagnostics remain available.

`--reference-postgres` labels a run as an ordinary PostgreSQL reference and is
restricted to localhost. Only that explicit mode permits `OC_TEST_PGSSLMODE=disable`.
CI uses this mode against PostgreSQL 18; it never contacts OriginChainDB.

## Development and remaining work

```sh
python -m unittest discover -s tests -v
python -m pip install build ruff
ruff check .
ruff format --check .
python -m build
```

The [backend design](docs/backend-design.md) identifies integration points and
the [release gates](docs/release-gates.md) define the work required before a
working Frappe/ERPNext distribution can be claimed. A pass on eight probes is
only an input to that work.

This toolkit's original code is MIT licensed. Upstream source is linked rather
than bundled. Frappe's [MIT license](https://github.com/frappe/frappe/blob/v16.54.0/LICENSE)
and ERPNext's [GPLv3 license](https://github.com/frappe/erpnext/blob/v16.53.0/license.txt)
remain separate. This is not an upstream Frappe release or endorsement.

