# Gates for a working application release

The `0.1.0-alpha.1` toolkit release does not satisfy these gates. No combination
of its offline tests or reference PostgreSQL checks constitutes application parity.

| Gate | Required evidence | Initial status |
| --- | --- | --- |
| Engine baseline | Build ID, redacted capabilities, listener mode and exact topology | Not tested |
| SQL prerequisites | Eight workbench checks plus a complete application query inventory | Not tested on OriginChainDB |
| Backend implementation | Reviewed driver, schema, provisioning, query and backup integration | Not implemented |
| Fresh install | New site, ERPNext installation, setup wizard, company and chart of accounts | Not tested |
| Framework | Complete upstream test suite, permissions, DocTypes, workflows, APIs and jobs | Not tested |
| ERPNext | Complete upstream test suite on the same engine baseline | Not tested |
| Accounting | Invoice/payment posting, taxes, currencies, rounding, GL and reconciliation | Not tested |
| Inventory | Receipts, deliveries, returns, stock entries, batches/serials and valuation | Not tested |
| Concurrency | Naming series, document conflicts, reservations, deadlocks and retry boundaries | Not tested |
| Data lifecycle | Import/export, migrations, upgrade/restart, backup and restore with comparison | Not tested |
| Application UI | Desk login, forms, reports, printing and representative end-to-end workflows | Not tested |
| Failure recovery | Connection loss around commit, timeouts, restart/failover and duplicate prevention | Not tested |
| Performance | Workload-specific latency, throughput and resource use against baseline | Not measured |

Run upstream tests from the compatible Bench environment after the adapter exists:

```sh
bench --site oc-test.local run-tests --app frappe
bench --site oc-test.local run-tests --app erpnext
```

Capture the actual test totals, failures, skips and reasons. Do not mark a skipped
backend-dependent test as passed. Compare representative reports and ledger/stock
balances to the MariaDB baseline using the same fixtures. Exercise upgrade from
an earlier supported version and verify restored data before claiming migration
support. Document the supported versions and any explicit exclusions.

An experimental adapter may be released once it installs and its demonstrated
subset is clearly stated. A stable release requires the applicable gates above
and a support matrix based on recorded runs. Arbitrary third-party apps and custom
SQL reports require their own validation.

