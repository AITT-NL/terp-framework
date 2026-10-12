# Platform reach — the open items

> **Origin:** distilled from `PLATFORM_REACH.md`, a design document drafted on 2026-09-04
> against 0.17.0 beside [ADR 0181](../../decisions/0181-terp-supplies-the-inside-of-a-deployable.md).
> The full text, with every item worked through to its seam, enforcement, failure modes and
> tests, is kept at
> [commit db40d288](https://github.com/AITT-NL/terp-framework/blob/db40d288dfe7a3d83c25da240eebbff4940e7098/docs/internal/PLATFORM_REACH.md).
> Checked against 0.34.0 on 2026-10-12: what main has built or decided since is listed once
> and dropped, and the rest keeps only what is still missing.
>
> **Audience:** platform/core team + agents. **Status:** proposals, none scheduled. An item
> becomes work through its own ADR, not through this file.

The draft's argument in one line: *permitted is not supplied*. A shape nothing refuses can
still be a shape the platform gives no parts for, and an author finds that out one missing
part at a time. ADR 0181 makes the argument for the space between deployables; the
application items below have the same shape one level down.

## Done or decided since the draft

| Item | What main did |
|---|---|
| R1 egress capability | Built: `terp-cap-egress` (ADR 0117), one transport (ADR 0144), refused at the socket (ADR 0177). Its leftovers are listed below. |
| R7 chart primitive and data palette | Built: ADR 0158, amended by ADR 0169 §6 — `react-core/src/charts/`, `DashboardPage`, `--color-chart-1..5`. The admin hub (ADR 0171) is the first consumer. |
| R10 screens that are not a record | Built in another form: `WorkspacePage` and `CanvasHost` (ADR 0179). The draft's relaxed-styling component zone is refused: ADR 0175 holds all of `src/**` to the boundary rules. |
| R12 public surfaces, backend half | Built: a route declares its own public posture (ADR 0148). Marketing sites are not a Terp application kind (ADR 0123), which matches R12's own out-of-scope. |

## The between — ADR 0181 decision 4

| Item | Still missing on 0.34.0 | Already beside it |
|---|---|---|
| R1 leftovers | Bounded retry with jitter, a breaker, sealed credential custody, egress audit (named open in ADR 0117), outbound correlation headers | The capability itself; its observer hook is where audit attaches |
| R2 event relay | `terp-cap-relay`: drained outbox rows whose event is marked `external=True` are published to a broker; `terp relay consume` dedupes and runs `dispatch_in_process` in the consumer's own transaction. At-least-once, no dual write | `dispatch_in_process` is the only dispatcher; ADR 0176's Redis broker carries realtime publishes, not domain events |
| R3 trace context | W3C `traceparent` parsed and emitted by the request-id middleware; propagated through egress, the job envelope and the relay envelope; the exporter lives in an opt-in `terp-cap-otel`, never in `terp.core` | The request-id context var; the job envelope already carries `request_id`; STATUS.md records OTel wiring as deferred |
| R4 deploy-unit declaration | Spec vocabulary for units, image, health path, migration owner and rollback; `unmanaged: true` with a required reason. Best folded into ADR 0111 decision 5 rather than kept separate | ADR 0111 decision 5 (unbuilt); the environment manifest's per-service visibility (ADR 0124) and `requiredIn` (ADR 0180) |
| R5 audience-scoped tokens | A mandatory, checked `aud`; `POST /auth/token/exchange` returning a short-lived token with an RFC 8693 `act` claim for the human; a per-principal audience allowlist, refused and audited when ungranted | `TOKEN_AUDIENCE` is fixed to `terp.api`; the job actor (ADR 0125, 0129) covers a broker hop, not an HTTP one |

## Application reach

| Item | Still missing on 0.34.0 | Already beside it |
|---|---|---|
| R6 aggregation seam | A sanctioned scoped aggregate: `Measure` / `Dimension` / `TimeBucket` declared on the service like filters and sorts, composed on `base_query()` as a subquery, returned as `Page[Bucket]` under a cardinality cap. And a runtime backstop for aggregate selects | See the correction below |
| R8 search seam | `searchable = (SearchField(...),)` on the service and `service.search(q=...)` returning a ranked `Page[T]` on `base_query()`, with the framework owning the index and the dialect difference | Only the `contains` filter (`core/filtering.py`) |
| R9 model calls and streaming | `kind="model"` defaults on egress (long read timeout, retries off), a `{ seq, delta, done }` chunk envelope over realtime, a token budget, prompt redaction in the audit record | The call goes through egress; slow work is a job; realtime has a shared broker (ADR 0176); ADR 0111 §4 declined a dedicated AI capability |
| R11 data Terp does not own | `ExternalTable` and `ReadOnlyService` for a view or table another owner manages: no managed id, no migrations, no writes | Companion roots (ADR 0141) now gate the package a foreign connector lives in |
| R12 public surfaces, frontend half | `public: true` on `ModuleRoute`; `PublicShell` and `PublicPage`; a `terp verify` check that the frontend's public routes and the backend's public policies agree; a public policy implies `require_shared_throttle_store` in production | The backend half (ADR 0148) |
| R13 governed-zone map | `terp check --explain <path>`; a `terp guide zones` topic; `gate: "terp" \| "external"` on workbench and deploy units | Which rules apply where (ADR 0136, 0175); `RULE_ROOT_KINDS` and the per-root "held to" report (ADR 0141) |
| R14 the consumer test | The amendment to ADR 0099 ("…or two independent applications asked for it") and a countable request ledger | The two-observation bar is applied in practice (ADR 0158, 0169, 0179), without a formal amendment or a ledger |

**R6, a correction to the draft.** The draft argued that a hand-built sum over a
tenant-scoped model slips past every control. On 0.34.0 that is half true. The build-time
rule is not blind to it: `reads_use_base_query` walks the whole `select(...)` chain, so
`select(func.sum(Invoice.amount))` over a scoped model is flagged
(`terp/arch/rules/traits.py`). The runtime half is: the session guard re-scopes only a
single-entity select and leaves a column or aggregate select untouched
(`terp/core/_internal/session_guard.py`). So the gap is a missing sanctioned path plus a
missing runtime backstop, not an invisible hole. ADR 0171 hand-writes one framework-owned
aggregate in `terp-cap-audit`, which is the shape a seam would replace.

## Refused in the draft, with the alternative

Recorded so they are argued once rather than re-proposed:

- **Asynchronous persistence.** A request that fans out to slow dependencies is a job; an
  application dominated by that shape is a gateway, and a gateway is a sidecar.
- **A non-relational primary store.** JSONB for document-shaped columns; a sidecar for a
  genuinely different store; R11 to read what another system owns.
- **High-volume ingest through `BaseService`.** A sidecar writes its own table, and the app
  reads it through R11.
- **Offline-first client sync.** None supplied; an application that needs it should learn
  that before it chooses the platform.
- **Micro-frontends or a federated shell.** Several typed clients in one shell, or a
  separate product on the same contract.
- **Server-side rendering.** A public marketing site is not a Terp application (ADR 0123).
- **A query language or pivot builder.** A database view plus a read-only model (R11).
- **A second table component, and the rest of ADR 0099's thirteen.** Unchanged.

## Open questions that still stand

- R2's broker: the first adapter should be the one the platform's own deployments run.
- R6's cardinality probe: a sampled estimate, a `LIMIT` probe that fails on overflow, or a
  declared-only cap; benchmark before choosing.
- R11's dialect tier: whether the platform supports what an application certifies against
  its own dialect is a commercial question.
- Where R14's ledger lives.
