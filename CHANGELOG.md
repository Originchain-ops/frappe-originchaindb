# Changelog

## 0.2.0-alpha.1 — experimental backend branch

- Add a real Frappe PostgreSQL-derived database class with explicit OriginChainDB identity.
- Add managed empty-schema bootstrap, experimental Bench creation command and pinned patches.
- Require verified TLS remotely and preserve repeatable-read isolation.
- Guard implicit DDL commits; disable unsupported database lifecycle and dump/restore operations.
- Adapt two ERPNext aggregation paths and add real application reference CI.

OriginChainDB execution and full Frappe/ERPNext functionality remain unverified.

## 0.1.0-alpha.1 — 2026-10-31

Initial compatibility toolkit for a future Frappe + ERPNext OriginChainDB port.

- Reproducible audit of nine source requirements on pinned upstream commits.
- Eight behavioral PostgreSQL-wire probes with isolated scratch tables and cleanup reporting.
- Explicit disposable-test configuration, verified TLS for remote tests, and sanitized errors.
- Offline guard tests, a PostgreSQL 18 reference CI job, and Python package artifacts.
- Candidate backend design and application release gates.

No backend adapter is implemented. No OriginChainDB instance or Frappe/ERPNext
application was run. This release does not replace MariaDB or establish full
functionality.

