# Candidate backend design

Status: experimental implementation in `frappe_originchaindb/`, with pinned
integration patches in `integration/patches/`. Target: Frappe + ERPNext v16.
No OriginChainDB instance has been used. The notes below include remaining work.

Start by testing the actual OriginChainDB PostgreSQL listener. Reusing the driver
and parts of Frappe's PostgreSQL backend is a candidate approach, subject to
transaction, SQL, catalog and driver compatibility results.

## Integration points

- **Backend selection:** extend Frappe's database factory, site configuration,
  Bench commands and query-builder mapping with an explicit OriginChainDB backend.
  Keep engine identity separate from SQL dialect. Audit `db_type` comparisons and
  `multisql` branches before introducing a new value.
- **Connections:** use the exact supplied SQL host, port, database, SQL identity and
  TLS trust. Verify a real writable session. Record the engine build, capability
  response and deployment topology as evidence, without credentials.
- **Transactions:** preserve rollback, savepoints, locking and request/job transaction
  boundaries. Reject an unsupported required isolation level. Changing application
  concurrency to optimistic retries would be a separate behavioral change requiring
  tests for naming series, stock reservations and ledger posting.
- **Site creation:** support a deliberately provisioned managed database without
  assuming the application can create database users or issue administrative grants.
  Design tenant isolation explicitly; a shared schema must not accidentally expose
  another site's records. Do not substitute local files for the main database.
- **DocType schemas:** implement type mapping, schema introspection, table/index
  changes, constraints and migration recovery against the actual supported catalog.
  Validate generated SQL with spaces and case-sensitive DocType identifiers.
- **ERPNext queries:** replace direct dialect-specific aggregates with tested
  database-aware expressions. Test each affected report's results on both the
  baseline database and OriginChainDB; syntax success alone is insufficient.
- **Backup and restore:** implement and verify a supported export/restore path.
  Do not assume `pg_dump` compatibility solely from the wire protocol.
- **Other services:** retain Frappe's Redis caches/queues, web workers, scheduler,
  realtime service, file storage and PDF services while changing the relational store.

## Evidence needed before choosing the implementation

For each prerequisite failure, distinguish driver setup, permissions, SQL translation,
engine semantics and deployment restrictions. A patch should fix a known mismatch;
it must not swallow errors, fabricate catalog responses, downgrade isolation, or
turn commit/rollback into no-ops.

The adapter requires explicit experimental opt-in. `db_type=postgres` retains the
upstream SQL dialect, while `db_backend=originchaindb` selects the subclass before
site initialization. Public docs cannot establish the endpoint's behavior. The
connection forces repeatable read and fails before writes if it is refused. Native
dump/restore and managed database/user deletion are explicitly disabled.

