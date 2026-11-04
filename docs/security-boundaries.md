# Security boundaries and regression evidence

The security fixes target the result of an operation sequence: which rows a caller can
see, what remains after a denied write, and which authority a credential carries after a
concurrent change. An exception or a successful source check alone does not prove those
properties. The tests below use real persistence and framework services, with local
transport servers where the transport itself is the boundary.

| Runtime scenario | Regression evidence |
|---|---|
| Permission role floor and grant, including projection parity | `tests/architecture/test_permission_floors.py`, `test_permission_projection.py` |
| Current authorization before cached-response replay | `apps/example/tests/test_idempotency_authorization.py`, `tests/architecture/test_idempotency.py` |
| Revoked grants on established realtime streams | `tests/architecture/test_realtime_revocation.py` |
| Related-entity scope | `tests/architecture/test_persistence_isolation.py` |
| Denied mutation followed by another commit | `tests/architecture/test_object_authz.py`, `test_persistence_isolation.py` |
| Consistent authenticated authority and epoch | `apps/example/tests/test_authentication_snapshots.py`, `tests/architecture/test_service_principals.py` |
| Login bound to the initiating browser | `tests/architecture/test_oidc.py` |
| Cookie-only server-side logout, including concurrent PostgreSQL rotation | `apps/example/tests/test_authentication_snapshots.py`, `tests/architecture/test_refresh_concurrency_postgres.py` |
| Body-carried logout and the authenticated epoch on native refresh | `apps/example/tests/test_native_sessions.py` |
| Single-use refresh rotation and reuse detection, cookie and body carriers | `apps/example/tests/test_runtime_security_cases.py`, `test_refresh_tokens.py`, `test_native_refresh.py` |
| Routes that return a refresh token in the body refuse browser provenance | `apps/example/tests/test_runtime_security_cases.py`, `test_native_refresh.py` |
| Self-service accounts: identical answers, proof of address, sealed single-use expiring tokens, backoff, lowest rank and closing | `apps/example/tests/test_runtime_security_cases.py`, `tests/architecture/test_self_service_accounts.py` |
| Stale worker finalization and job rollback | `tests/architecture/test_worker_transactions.py` |
| Sync failure journal with rolled-back business changes | `tests/architecture/test_sync_transactions.py` |
| Visible source custody without committing business work | `tests/architecture/test_sync_custody.py` (PostgreSQL and SQLite) |
| Outbound allocation and elapsed network budgets | `tests/architecture/test_egress_limits.py` |
| Rendered credential redaction | `tests/architecture/test_structured_logs.py` |
| Validated encrypted mail configuration | `tests/architecture/test_mail.py` |
| Authenticated webhook routing and replay metadata | `tests/architecture/test_webhooks.py` |
| Authority to bind a file reference | `tests/architecture/test_file_binding.py` |

Run the framework gate with `uv run coverage run -m pytest` and `uv run coverage report`.
Set `TERP_TEST_POSTGRES_URL` to a disposable PostgreSQL server when running the full
coverage gate locally. PostgreSQL-specific sync custody paths need a real server;
skipping them leaves the 100% coverage gate incomplete. CI supplies PostgreSQL 17 to
the coverage job, while the dedicated PostgreSQL lane also installs the matching
restore client and refuses skipped restore drills.
The minimum-runtime-security CI lane independently resolves the lowest allowed direct
dependencies, audits its external runtime tree, and exercises the relevant boundaries.
The normal gate and dependency audit cover the current resolution. These checks complement
the source-rule corpus; they are not inferred from its scorecard or from coverage alone.
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
