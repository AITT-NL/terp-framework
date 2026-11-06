# Security boundaries and regression evidence

The security fixes target the result of an operation sequence: which rows a caller can
see, what remains after a denied write, and which authority a credential carries after a
concurrent change. An exception or a successful source check alone does not prove those
properties. The tests below use real persistence and framework services, with local
transport servers where the transport itself is the boundary.

Each row names the runtime security case it is evidence for (the `id` in
[`tests/runtime_security/runtime-security.fixtures.json`](../tests/runtime_security/runtime-security.fixtures.json)),
and each piece of evidence is a test file, or a test function in one, that runs it.
`tests/architecture/test_runtime_security_evidence.py` holds the index to those cases: every
case has a row, every case a row names is one the fixtures have, and every file and function
named exists. A case, its row and its tests land in one change.

| Case | Runtime scenario | Regression evidence |
|---|---|---|
| `permissions.floor-and-grant` | Permission role floor and grant, including projection parity | `tests/architecture/test_permission_floors.py`, `tests/architecture/test_permission_projection.py` |
| `replay.current-authority` | Current authorization before cached-response replay | `apps/example/tests/test_idempotency_authorization.py`, `tests/architecture/test_idempotency.py` |
| `streams.current-grants` | Revoked grants on established realtime streams | `tests/architecture/test_realtime_revocation.py` |
| `scope.relationships` | Related-entity scope | `tests/architecture/test_persistence_isolation.py` |
| `writes.denial` | Denied mutation followed by another commit | `tests/architecture/test_object_authz.py`, `tests/architecture/test_persistence_isolation.py`, `tests/architecture/test_refused_delete.py` |
| `tokens.snapshot` | Consistent authenticated authority and epoch | `apps/example/tests/test_authentication_snapshots.py`, `tests/architecture/test_service_principals.py` |
| `oidc.browser-binding` | Login bound to the initiating browser | `tests/architecture/test_oidc.py` |
| `sessions.logout` | Cookie-only server-side logout, including concurrent PostgreSQL rotation | `apps/example/tests/test_authentication_snapshots.py`, `tests/architecture/test_refresh_concurrency_postgres.py` |
| `sessions.logout`, `tokens.snapshot` | Body-carried logout, and the authenticated epoch on native sign-in and refresh | `apps/example/tests/test_native_sessions.py` |
| `sessions.rotation` | Refresh rotation and reuse detection outside the grace window, cookie and body carriers | `apps/example/tests/test_runtime_security_cases.py::test_case_sessions_rotation`, `apps/example/tests/test_refresh_tokens.py`, `apps/example/tests/test_native_refresh.py` |
| `native.browser-refused` | Routes that return a refresh token in the body refuse browser provenance before reading the body | `apps/example/tests/test_runtime_security_cases.py::test_case_native_browser_refused`, `apps/example/tests/test_native_refresh.py` |
| `accounts.enumeration` | Self-service: a request about an address answers alike, and sends it one message, whatever the address | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_enumeration`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.proof-of-address` | Self-service: an account opens only when its mailed token is redeemed, with the password chosen then | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_proof_of_address`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.single-use` | Self-service: a token works once, and a reset token dies with a later revocation | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_single_use`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.sealed-tokens` | Self-service: a token cannot be read or altered, and rides only the link's fragment | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_sealed_tokens`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.expiry` | Self-service: a token dies with its lifetime, bounded at a week and a day | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_expiry`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.backoff` | Self-service: requests back off per caller and never lock out | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_backoff`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.lowest-rank` | Self-service: a self-registered account starts with the least authority | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_lowest_rank`, `tests/architecture/test_self_service_accounts.py` |
| `accounts.close` | Self-service: closing takes the password again and ends every session | `apps/example/tests/test_runtime_security_cases.py::test_case_accounts_close`, `tests/architecture/test_self_service_accounts.py` |
| `outbox.finalize`, `jobs.atomicity` | Stale worker finalization and job rollback | `tests/architecture/test_worker_transactions.py` |
| `jobs.atomicity` | Sync failure journal with rolled-back business changes | `tests/architecture/test_sync_transactions.py` |
| `leases.protected-effects` | Visible source custody without committing business work, PostgreSQL and SQLite | `tests/architecture/test_sync_custody.py` |
| `egress.budgets` | Outbound allocation and elapsed network budgets | `tests/architecture/test_egress_limits.py` |
| `logs.redaction` | Rendered credential redaction | `tests/architecture/test_structured_logs.py` |
| `config.transport` | Validated encrypted mail configuration | `tests/architecture/test_mail.py` |
| `webhooks.envelope` | Authenticated webhook routing and replay metadata | `tests/architecture/test_webhooks.py` |
| `files.binding` | Authority to bind a file reference | `tests/architecture/test_file_binding.py` |

Run the framework gate with `uv run coverage run -m pytest` and `uv run coverage report`.
Set `TERP_TEST_POSTGRES_URL` to a disposable PostgreSQL server when running the full
coverage gate locally. PostgreSQL-specific sync custody paths need a real server;
skipping them leaves the 100% coverage gate incomplete. CI supplies PostgreSQL 17 to
the coverage job, while the dedicated PostgreSQL lane also installs the matching
restore client and refuses skipped restore drills.
The minimum-runtime-security CI lane independently resolves the lowest allowed direct
dependencies, audits its external runtime tree, and exercises the relevant boundaries.
The normal gate and dependency audit cover the current resolution. These checks complement
the source-rule corpus; they are not inferred from it or from coverage alone.
The decisions and remaining boundaries are recorded in
[ADR 0193](decisions/0193-security-boundaries-hold-across-operation-sequences.md).

## Compatibility

Custom authentication and refresh callbacks must migrate as described in
[authentication transitions](authentication-transitions.md). Run the identity migrations
before starting the updated application. Webhook receivers must adopt
[signature version 2](webhook-signatures.md) with the sender. Outbound HTTP requires
identity encoding and applies the [documented resolver limitation](../packages/backend/capabilities/egress/README.md).
Routes that return stored idempotent responses must follow
[replay authorization](idempotency-authorization.md), including checking the original
result's resources and preserving the request inputs used by the fingerprint.
Permission dependencies require registered permissions and enforce their declared floor;
see [access migration](../packages/backend/capabilities/access/README.md).
Live streams require fresh authority lookups, with idle revocation bounded by the
[heartbeat interval and provider latency](../packages/backend/capabilities/realtime/README.md).
Keep each ORM session within one authority context. Scoped database loads do not erase
entity attributes or relationship collections already loaded into memory before a
tenant or actor change; use a fresh session for the new context.

Jobs now have the atomic database transaction their API promises. External network effects
cannot be rolled back by that transaction; handlers still need idempotent external effects
and an explicit retry policy. Webhook attempt journals and sync failure records deliberately
survive failed jobs in a separate infrastructure transaction. The
[sync transaction contract](../packages/backend/capabilities/sync/README.md) describes what
the journal records after rollback and the source-custody guarantees.

## Remaining dependency advisory

The 3 November 2026 npm audit reports
[GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) in `deepmerge`
4.3.1 and its build-tool dependency path through `@bundled-es-modules/deepmerge` and
`style-dictionary`: three low-severity package entries for one advisory. No patched
`deepmerge` release was available when this change was prepared. npm's suggested downgrade
of the token builder is a major compatibility change, not a safe automatic fix.

This path builds tokens from the repository's reviewed theme sources; the application
request path does not feed user objects into it. The audit remains visible. Framework
maintainers own follow-up by **3 December 2026**, or earlier when a compatible fix becomes
available. That follow-up must either update and validate the builder or reassess this
limited exposure; it must not silently suppress the advisory. CI blocks new moderate or
higher npm findings, and the Python audit blocks every reported finding.
