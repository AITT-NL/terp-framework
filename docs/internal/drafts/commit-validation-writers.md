# Who owns each database write?

Phase 2a validates the ORM rows a service transaction commits in opted-in tests. A quote update can legitimately
write the quote, an audit entry and an outbox event together. Each writer can account for its
own change. The transaction owner must still check the complete unit before committing it.
This inventory covers the Python backend shipped by Terp and describes each writer’s
participation. The pytest report and validator use the same accepted states. [Declared rules design](declared-business-rules-design-and-plan.md)

## Writers and transaction ownership

| Writer | Current operation and transaction | How it should participate in validation |
| --- | --- | --- |
| Application and capability services | `BaseService._save` stages a row, `_remove` stages a hard delete, and a soft delete saves the retained row. Nested saves, including custom Python service methods, join the outer write. | Capture the accepted state for that row and operation. A subsequent save advances it. Compare every participating row at the outer commit, including one issued by the job runner. [Base service](../../../packages/backend/core/src/terp/core/base_service.py) · [Job runner](../../../packages/backend/core/src/terp/core/_internal/job_runtime.py) |
| Audit | The durable sink appends an `AuditEvent` to the business transaction. `emit_disclosure` opens a separate transaction to record a read before handing over data. | Account for the exact appended audit row in its owning transaction. A failed business write rolls its audit entry back. A completed disclosure has its own durable record. [Sink](../../../packages/backend/capabilities/audit/src/terp/capabilities/audit/sink.py) · [Disclosure](../../../packages/backend/core/src/terp/core/audit.py) |
| Refresh-token lifecycle | The identity service inserts, changes and retires `RefreshToken` rows. Rotation and revocation can affect multiple rows in one unit. The outermost operation owns the commit. | Record the expected insert, field changes or delete for each affected token. Keep ordinary user-profile changes on their service path. [Refresh service](../../../packages/backend/capabilities/identity/src/terp/capabilities/identity/refresh.py) · [User service](../../../packages/backend/capabilities/users/src/terp/capabilities/users/service.py) |
| Outbox and schedule ledger | A producer appends an `OutboxMessage`. Workers claim, finalize and release messages with conditional SQL. The scheduler settles a `ScheduleFire` and its queued job, when due, in one unit. | Validate the producer’s append alongside the business row. Preserve the worker and scheduler statement predicates, the fields each operation can change and their affected-row checks. A lost schedule update must also roll back its enqueue. [Outbox and schedule store](../../../packages/backend/capabilities/outbox/src/terp/capabilities/outbox/store.py) |
| Resource leases | The database lease store creates a `ResourceLease` and uses conditional SQL for acquisition, renewal, release, forfeit and purge. A reaper can run a domain callback in the same transaction. | Keep the lease store’s ownership and expiry predicates on its statements. Validate domain rows written by the callback through their own services. Sync custody can have its own transaction on PostgreSQL and shares the business connection during a SQLite job. [Lease store](../../../packages/backend/capabilities/leases/src/terp/capabilities/leases/store.py) · [Reaper](../../../packages/backend/capabilities/leases/src/terp/capabilities/leases/reaper.py) · [Sync custody](../../../packages/backend/capabilities/sync/src/terp/capabilities/sync/leasing.py) |
| Sync records and failed-run journal | A `SyncRecordLog` append joins local changes when nested. `SyncMapping` and `SyncRun` use services. A job can record a failed run through a fresh guarded session after its business transaction finishes. | Validate each log append in its own unit. Apply normal service validation to the failed-run journal in the new transaction. After a rollback, only the intended attempt record may persist from that failure. [Record log](../../../packages/backend/capabilities/sync/src/terp/capabilities/sync/store.py) · [Sync service](../../../packages/backend/capabilities/sync/src/terp/capabilities/sync/service.py) |
| Webhook delivery attempts | `record_delivery` appends a `WebhookDelivery`. Inside a job it defers the attempt record until the job transaction finishes, then uses a fresh connection. | Account for the immutable append in the transaction that actually writes it. A failed attempt can remain observable while the failed business changes roll back. [Delivery store](../../../packages/backend/capabilities/webhooks/src/terp/capabilities/webhooks/store.py) |

An accepted infrastructure write identifies its row, operation and expected values or deletion.
For a conditional SQL operation, its store owns the statement and checks the outcome under its
existing concurrency contract. Entering a write unit determines who commits. Each writer must
still account for its own rows, including when several writers share a session. A savepoint
rollback discards the changes accepted within that savepoint. A new transaction starts with
its own record of accepted writes. [Write observer](../../../packages/backend/core/src/terp/core/_write_report.py)

Framework-assigned columns have a separate role. A soft delete sets `deleted_at` through
the service. A declared invariant that reads that timestamp must see its proposed value,
even though client input cannot set it. [Managed input columns](../../../packages/backend/core/src/terp/core/_service_writes.py)

## Writes owned by the database or maintenance tools

- **Foreign-key actions.** The database can delete a dependent row or set a surviving row’s
  reference to null. For a rule that reads an affected column, test the actual parent deletion
  on both supported databases. The design calls for a boot refusal while a combination cannot
  be enforced. [Reference declarations](../../../packages/backend/core/src/terp/core/references.py)
- **Secret re-sealing.** The CLI uses a connection-level conditional update to replace a sealed
  value while preserving its logical content, row version and update timestamp. Keep its batch
  transaction, comparison with the previous value and maintenance tests. [Re-seal implementation](../../../packages/backend/cli/src/terp/cli/reseal.py)
- **Migrations and backfills.** The migration engine owns its revision and schema-window
  records. A data migration that changes business values needs post-migration checks over
  the affected data. The design proposes `terp rules check-data` for this purpose.
  [Migration window](../../../packages/backend/migrations/src/terp/migrations/window.py) · [Data checks](declared-business-rules-design-and-plan.md#38-stored-rows-are-checked-against-the-rules-on-demand)

## What the observer saw

Before the infrastructure writers recorded their own operations, running
`pytest --terp-report-writes apps/example/tests` on SQLite passed 282 tests and
observed 769 committed ORM write transactions. Of the 633 transactions with findings, 632
had findings confined to framework models. One included a journal row inserted as test setup.
The counts below are transactions with a finding for that model. A transaction can appear
in more than one row. [Example fixtures](../../../apps/example/tests/conftest.py) · [Journal fixture use](../../../apps/example/tests/test_journal_visibility.py)

| Model | Transactions |
| --- | ---: |
| `AuditEvent` | 325 |
| `RefreshToken` | 181 |
| `User` | 130 |
| `OutboxMessage` | 1 |
| `WebhookDelivery` | 1 |
| `Journal` (example application) | 1 |

The report attributes ORM flushes to a test and model. It includes fixture setup. The
write site determines which operation owns a row. For example, the shared user fixture
inserts a user directly, while application user changes normally use a service. SQL
statements, database referential actions and maintenance connections need their own evidence.

With the infrastructure writers participating, the same 282 example tests passed and
the report counted 769 ORM write transactions. Of those, 136 still had findings.

| Remaining operation | Transactions |
| --- | ---: |
| User insert | 124 |
| User active-status change | 6 |
| Refresh-token expiry change | 5 |
| Journal fixture insert | 1 |

The five expiry changes set up expired test data. These counts identified the fixtures
to migrate before enabling refusal throughout the example suite.

## Running the shipped examples with refusal enabled

The example suite now requests `terp_validate_writes` for every test. The shared
user setup saves synthetic identities through a test service. Admin changes and
journal creation go through their ordinary services. Tests of an independently
deactivated user preserve its token epoch and assert that precondition. Expiry
tests advance the refresh store’s clock so the original credential can expire while
its successor stays live. The audit tests count the note operations they exercise,
including when provisioning the test actors also emits audit records.

| Suite | Tests passed | Committed ORM write transactions | Findings |
| --- | ---: | ---: | ---: |
| Example application (SQLite) | 282 | 767 | 0 |
| Default template (SQLite and PostgreSQL 17) | 8 | 0 | 0 |
| Rendered reference application (SQLite and PostgreSQL 17) | 48 | 48 | 0 |

Both renders used the local framework wheels. The blank template tests architecture
and migration conformance. The reference overlay also exercises requests, jobs and
their ORM writes. Template acceptance passes `--terp-validate-writes` when it tests
each render. [Example fixtures](../../../apps/example/tests/conftest.py) ·
[Reference tests](../../../apps/reference/overlay/tests) ·
[Acceptance workflow](../../../.github/workflows/ci.yml)

The [quote transaction cases](../../../tests/architecture/test_quote_persistence.py) use the validator
on SQLite and PostgreSQL. A request or job that changes the accepted margin after the revision
and event were staged rolls back those rows and its audit entries. The
[webhook journal](../../../tests/architecture/test_webhooks.py),
[sync custody](../../../tests/architecture/test_sync_custody.py) and
[scheduler](../../../tests/architecture/test_scheduler_adapters.py) tests also exercise
validation with an independently durable journal and with conditional store updates.
