# Terp — build status & remaining work

> **Living checklist.** This tracks *what's built* and *what's left*, at a glance.
> It is deliberately thin: the **authoritative plan** is
> [`AGENTIC_PLATFORM_DESIGN.md` §13](../AGENTIC_PLATFORM_DESIGN.md) and the
> **authoritative rationale** is
> [ADR 0001](decisions/0001-terp-namespace-and-kernel-scope.md). When this file
> disagrees with those, **they win — fix this file.**
>
> **Keeping it current:** tick a box when an increment lands green; when an
> increment is a *decision* (not just a checkbox), also add an ADR decision.

**Snapshot — 2026-07-05:** **1097 tests passing** (+ the env-gated PostgreSQL
conformance lane, ADR 0069), **100% framework line coverage**
(`.\.venv\Scripts\python.exe -m pytest --cov=terp`). A shipped `terp-core`
kernel + the `terp-arch` harness; Phase 2 (capabilities) is in progress, and the
control-plane refinement has landed Phases A/B-keystone + **Phase C (security
middleware + structured logging, ADR 0005)**, hardened (ADR 0006), **Phase D
(audit auto-emit, ADR 0007)**, and the **Phase D event bus (typed `EventCatalog`
+ NO-DRIFT `emit`, ADR 0008)**, plus the declarative authoring traits (ADRs
0009–0012: lifecycle event map, auto-honored soft-delete, actor-stamping),
**adversarial-review hardening (ADR 0014)**, a **runtime write-guarded
session (ADR 0015)**, and **per-subject permission enforcement (ADR 0016)**, and a **non-overridable scope
predicate + row-scope registry (ADR 0017)**, the first **agent-onboarding
surface (`terp guide`, ADR 0019)**, a **response-model data-leak guard
(`response_model` may not be a table model, ADR 0020)**, a **first-class
middleware composition seam (`create_app(middleware=…)`, ADR 0021)**, and a
**role-model-agnostic, tenant-aware login (ADR 0022)** — completing the
adversarial-review (ADR 0014) structural follow-ups — and the **`build_crud_router`
Tier-C CRUD factory (ADR 0023)**, and **built-in health/readiness endpoints +
connection-pool config (ADR 0024)**, and **medium-severity input/observability
hardening (M2/M3/M6/M8 — route-correlated input caps, no-body response exemption,
over-posting strip + rule, structured-log `extra=` emission; ADR 0025)**, and a
second **adversarial-review hardening batch (F1–F5): a runtime row-scope backstop
for custom reads + the strengthened `reads_use_base_query` rule (including
`self.model`, multi-entity selects, and `select_from`), enforced list pagination
(`list_routes_paginate`, including `api_route` and raw `list`), the engine-escape
`connection()` guard + the narrowed `no_raw_connection_access` rule, a re-closed
`_after_write` write scope, explicit tenant fail-closed scoping, ContextVar reset
coverage, and the tenancy middleware-seam doc fix (ADR 0026)**, and **packaged
migrations (Phase 7): independent per-package Alembic histories orchestrated by
`terp migrate`, a pure `terp.core.migrations` discovery seam, the `terp-migrations`
package, and a fail-closed pending-migrations boot guard (ADR 0027)**, hardened after
a pre-release red-team (cross-package FK autogenerate + FK-dependency-ordered upgrade,
SQLite-only batch mode, `stamp` / `heads` / `merge` / labelled `downgrade`, app-module
boot-guard coverage, fail-closed homeless-table detection, and the reusable
`assert_migrations_match_models` drift check). The
cross-cutting controls roadmap + opinionation policy is
[IMPLEMENTATION_PLAN §10](IMPLEMENTATION_PLAN.md) / ADR 0006. A **third
adversarial-review batch (F1–F3, ADR 0028)** then closed the read-path and
authorization-tier leaks a fix audit surfaced: the request session now re-scopes a
primary-key `get` / `scalars` / `scalar` (not only `exec`), a safe HTTP method
(GET/HEAD/OPTIONS) is refused a write at runtime and by the new
`safe_methods_are_read_only` rule, and the new `tables_have_migrations` rule fails the
build when an app module ships a table model with no migration. An
**object-level (ownership) authorization seam (ADR 0029)** then closed the per-row
write gap: a model composes the new `OwnedMixin`, and the `BaseService` chokepoint
stamps `owner_id` from the request actor on create and authorizes every update/delete of
an owned row per-row (a non-owner write fails closed 403) — with a capability registry
(`register_object_authz_predicate`) for richer policies, a build-time
`no_manual_ownership_checks` rule replacing the hand-rolled check, and the new
owner-scoped `journals` example module dogfooding it. Read visibility stays the separate
scope-predicate seam (ADR 0017), so endpoint (ADR 0016), row-read (ADR 0017), and
row-write (ADR 0029) authority now form the complete matrix. Finally, an
**agent-surface completeness ("docs can't lie") parity layer (ADR 0030)** makes the
agent-facing docs self-enforcing: `terp guide rules` is now generated from the live
`_ALL_RULES` registry, and build-time parity meta-tests fail the gate if a rule, model
trait, or capability seam ships without a `terp guide` recipe / `AGENTS.md` line, or if an
"enforced by `X`" claim no longer resolves — realizing the ADR-0019 "docs can't lie"
item and retroactively documenting the ADR-0029 ownership seam. Most recently,
**session-management hardening (ADR 0031)** closed the adversarial-review **M4** (no
token revocation) and **L3** (no login throttle) gaps: a per-user **token epoch**
(`token_version`) rides every access token, a revocable `get_principal` provider
(`build_get_principal(token_validator=…)`, wired in one call via
`IdentityService.principal_provider()`) re-checks `is_active` **and** the epoch every
request, and bumping the epoch on deactivate / role-change / password-reset / logout (a
new `POST /auth/logout`, through the audited `users` chokepoint) kills a still-unexpired
token mid-session; a per-account `LoginThrottle` (on by default, explicit
`LoginThrottle.disabled(reason=…)`) locks out credential stuffing with a typed 429; and
`create_app(require_token_revocation=True)` fails the boot closed unless a revocation-
enforcing provider is wired (the bundled stack sets it on, so the secure path is the
default). **Refresh-token sessions (ADR 0054)** now layer on that epoch: login issues an
opaque rotating refresh token in an httpOnly, path-scoped cookie, `/auth/refresh` rotates it
single-use with reuse-detection, and `UsersService.revoke_sessions` also kills refresh
families so logout / deactivate / demote / password-reset revoke both credentials. The React
provider keeps the access token memory-only but silently refreshes on boot, so a normal page
reload preserves the session without putting bearer tokens in web storage. Session management
is runtime/boot-only — no `terp.arch` AST rule applies (there is no module-authored pattern to
police), the honest two-layer shape per ADR 0006.
Finally, **password strength (ADR 0032)** closes the leading Tier-B gap: a `PasswordPolicy`
registry on `ControlPlane.passwords` (safe default 12+ chars, 2+ character classes, a
common-password denylist) is enforced fail-closed at the `users` credential boundary
(provision + reset raise a typed `WeakPasswordError`/422 before hashing; the `max_length`
DoS cap stays), `create_app` refuses to boot a relaxed policy in production, and
`PasswordPolicy.relaxed(reason=…)` is the justified opt-out — again runtime + boot only, no
AST rule. Finally, **generic CI backstops (ADR 0033)** complete Phase 3 by layering
off-the-shelf enforcement around the gate without weakening `terp-arch`: ruff bandit
(`select=['S']`, repo-wide clean), an `import-linter` `terp.core` layer-0 contract mirroring
the `test_core_boundary` keystone, and advisory `pip-audit` + `deptry` — all CI-only (a
separate `generic-checks` job + a `lint` dependency group), so the `uv run pytest --cov=terp`
gate stays unchanged and 100% green. Most recently, the **agent-visibility layer (Phase 6, ADR 0034)** lands: a
read-only, byte-exact mirror of the packaged kernel under `vendor/terp-core/` gives an
agent monorepo-level visibility into core without forking it, and
`test_vendored_core_unmodified` fails the gate closed if the mirror ever drifts from the
packaged source (purely additive — no `terp.*` logic changed; the mirror is never imported
and is `omit`-ed from coverage). Finally, the **distributed throttle store (ADR 0036)**
generalises the rate limiter and the per-account login lockout over one pluggable
`ThrottleStore` (default `InMemoryThrottleStore`, per-instance — unchanged): a multi-
instance deployment passes one shared backend so both limits are globally correct, a
store error fails closed, and the seam ships as the ADR-0006 quadruple with no AST rule
(runtime + kernel test only). Finally, **`BaseService` commit-ownership (ADR 0038)** closes
the last ADR-0001 Decision-9 deferral: the audited chokepoint owns the commit and the write
scope is now **re-entrant** (`enter_write_unit`) — the outermost `_save` / `_remove` commits
once and a nested write (an `_after_write` that re-enters via `self._save`) joins the same
transaction (stage + flush), so every write is one atomic, audited unit with no double-commit
or partial-txn footgun; `UnauditedWriteError` and the audit emit are unchanged (core-only).
Finally, the **universal rule set is complete (ADR 0037)**: the last four secure-by-default
fitness rules ship as AST rule + meta-test pairs — `schemas_exclude_sensitive_fields` (no
`*Read` DTO serializes a `password`/`hashed_password`/`*secret`/`*token`), `mutations_require_write_role`
(a mutating module's `Policy` write tier must outrank the read floor, never `VIEWER`),
`canonical_module_shape` (a `module.py` module carries `models`/`schemas`/`service`/`router`),
and `session_imported_from_sqlmodel` (the one canonical `Session`) — each surfaced in the
generated `terp guide rules`; the auth login `AccessToken` keeps a budgeted opt-out and the
example app stays `{}`.

Most recently, **Phase 5 scaffolding (ADR 0039)** lands the authoring ergonomics: `terp
new module <name>` emits the canonical five slots (passing every rule but the first
`terp migrate make`), a copier `template/` scaffolds a runnable base-profile app
(`create_app` + control plane + example module + CI), `terp api-docs` generates the
`.pyi` + reference from the live kernel (completing the Phase-1 deferral), and `terp
check` runs the gate locally — Tier-C sugar, never the only path.

Finally, a **fourth adversarial-review batch (ADR 0040)** corrects the most over-claimed
of the newest rules and closes four residual leaks. `mutations_require_write_role` is now a
**rank** comparison, not a literal-`VIEWER` match: a default-ladder inversion
(`Policy(read=ADMIN, write=EDITOR)`) is caught at build time, and the new boot check
`create_app → _validate_policy_write_tiers` is the universal runtime half that fails closed
on `write_rank < read_rank` for **any** role model (restoring the role-agnostic guarantee;
equality stays legal for flat / admin-only models). A new `public_modules_are_read_only`
rule flags an unauthenticated write (a `Policy.public` module with a mutating route),
justifiable only through a budgeted `# arch-allow-*` marker. `schemas_exclude_sensitive_fields`
now catches `secret_key` / `private_key` / `salt` / `pwd` (matched as underscore-delimited
words, with a *trailing*-only `token` so `token_type` stays clean). `terp api-docs` emits a
type-bearing `.pyi` (real signatures, not `(*args, **kwargs) -> Any`). And
`create_app(require_shared_throttle_store=True)` fails closed unless a shared, multi-instance
throttle backend is wired (mirroring the durable-audit-sink boot guard), so a horizontally
scaled deploy cannot silently dilute its rate limit / login lockout.

A small follow-up (**ADR 0042**) then closes two of that batch's open questions:
`canonical_module_shape` now treats any canonical file as a module claim, so a `modules/<name>/`
dir missing its `module.py` manifest (previously invisible to it *and* to
`modules_declare_policy`) is flagged; and the copier template CI regenerates the API contract
and `git diff --exit-code`s it, so a committed `docs/platform-api.md` can no longer silently
drift from the installed kernel.

Most recently, **Phase 4 (the frontend contract) kicks off (ADR 0041)** with its Python-side
source seam: `terp openapi` exports the live app's OpenAPI document — an app instance or a
zero-arg factory (`app.main:build`) — as sorted, indented JSON for the frontend codegen, so the
generated client (design §7.1) cannot drift from the backend, the same generate-don't-hand-write
instinct `terp api-docs` applies to the Python surface, now applied to the HTTP contract. It is
runtime + tooling only (no `terp.arch` AST rule); `test_cli_openapi` exercises the example app
and locks the ADR-0020 property at the contract boundary (no `*Read` schema serializes a
password). The example app's spec is now **committed as `packages/frontend/contract/openapi.json`
and drift-checked in the gate**: `test_openapi_contract` regenerates it from the live app and
fails closed if the committed copy fell behind (the committed-artifact + no-drift shape of the
vendored mirror, ADR 0034), so the frontend has a stable, reviewable input that cannot silently
diverge from the backend. The remaining `packages/frontend/*` packages stay stubs pending the
`@terp/contract` scaffolding (OpenAPI→typed client, design tokens, the route/nav manifest, and
the auth interface).

Most recently, the **jobs seam (ADR 0043)** lands the async/jobs design's Phase 1 — the core
job port, built "ports first, engines as adapters, sync last", shaped exactly like the event
bus (ADR 0008). `terp.core.jobs` defines a typed `JobDefinition` (a dotted name + a payload
schema + a handler resolved **by name** + a `RetryPolicy` + a routing `queue` +
`JobVisibility`), indexed in a `JobCatalog` that rejects duplicates (mirroring `EventCatalog`);
a JSON-serializable `JobEnvelope`; a one-method `JobQueue` ABC with a safe `InProcessJobQueue`
default that runs the handler inline in its own audited unit (no `threading` — the layer-0
boundary forbids a runtime thread in core); and the fail-closed `enqueue(session, *, job,
payload, idempotency_key=None)` chokepoint — the job analogue of `emit`, rejecting an
unregistered or shadowed job (`JobError`). The design's §7 (the highest-risk detail) is handled
in the internal `job_runtime` worker: it re-binds the envelope's actor (or a configured
control-plane **system actor** when no user originated the work), request id, and tenant
(through the new `register_job_tenant_context` seam, the job-side analogue of
`register_scope_predicate`) before invoking the handler — so **every write a job makes is still
audited and actor / tenant stamped, and tenant-isolated**, with no special-casing, proven by a
kernel test — including the subtle case where a job is enqueued from *inside* an audited write
or a read-only request: the runner opens a `fresh_write_scope` so the job is its own
independent, committed, audited unit rather than silently losing its write to an enclosing
scope on a different session. `create_app(..., job_queue=None, require_durable_jobs=False)`
validates every
declared `ModuleSpec.jobs` against the control plane's `JobCatalog` at boot and refuses a
non-durable queue when durability is required (`mark_durable_job_queue` /
`is_durable_job_queue`, mirroring the durable-audit-sink boot guard). The new
`jobs_reference_catalog` arch rule (paired with a meta-test, auto-surfaced in `terp guide
rules`) forbids a bare-string or inline-literal job, and `terp jobs run <name> --payload
<json>` (the external-scheduler trigger) + `terp jobs list` / `terp inspect jobs` (generated
from the live catalog) + a `terp guide jobs` authoring recipe complete the surface. The durable
outbox, engine adapters, scheduler
adapters, and the sync capability are deferred to later ADRs; the example app is untouched and
its escape-hatch budget stays `{}`.

Most recently, the **current-user `/me` endpoint (ADR 0044)** gives the frontend session
contract a real, server-validated source. Building `@terp/contract` surfaced that no exported
path returned the signed-in user and the access token carries no email (only id + role + tenant
+ epoch), with `GET /api/v1/users/{id}` ADMIN-only — so the UI would have had to trust decoded,
possibly stale token claims. A self-scoped `GET /api/v1/me` now ships on the auth surface via a
new `build_me_module` + an app-wired `CurrentUserResolver` seam (symmetric with `authenticate` /
`tenant_resolver` / `revoke_sessions`, so auth never imports the store): `IdentityService.current_user`
reads the **live** row through the revocable provider (ADR 0031) and returns `{id, email,
role_rank, role_name}`, so a deactivated / demoted token is already rejected and the response
reflects the store, not the token. Self-scope is structural (the handler reads only
`principal.id` and takes no id parameter), so it rides the existing guard + read-only binder with
no new AST rule (runtime / test-covered, the ADR-0031 precedent). The committed
`packages/frontend/contract/openapi.json` + `schema.d.ts` regenerate (gaining `/api/v1/me/` + the
`CurrentUser` schema), and `@terp/contract`'s `CurrentUser` is now reused from the generated
schema so it cannot drift; the role stays a numeric **rank** on the wire (ADR 0004 / 0022) with
`role_name` added for display only. No new table or migration; the example budget stays `{}`.

Most recently, the **durable outbox (ADR 0045)** lands the async/jobs design's Phase 2 — the
reliable, restart-surviving delivery the dispatcher seam (ADR 0008) was designed to receive and
the drop-in that makes the jobs seam (ADR 0043) durable. The opt-in **`terp-cap-outbox`** library
capability owns one append-only `outbox_message` table (`kind` = `event` | `job`, the serialized
envelope, `status`, `attempts`, the lease columns, and the `dispatched_at` / `dead_lettered_at` /
`last_error` timeline — `UUIDPrimaryKeyMixin`, not `BaseTable`, like `AuditEvent`), with its own
packaged Alembic history. A durable **`OutboxJobQueue`** (marked durable) and
**`outbox_event_dispatcher`** record their row **on the business write's own session**, riding the
audited `enter_write_unit` (ADR 0038) so it commits **atomically** with the mutation that produced
it and a rollback drops both — **no dual-write, no `enqueue` / `emit` call-site change** (ADR 0008's
promise). An **`OutboxWorker`** (`terp jobs worker`) leases due rows with a portable atomic UPDATE
(`SKIP LOCKED` on PostgreSQL; the lease serialises SQLite too), runs jobs through the kernel's
context-binding `run_job` (audited + actor / tenant stamped, §7) and events through the in-process
handlers, and retries with backoff / dead-letters per the `RetryPolicy` — **at-least-once**, with a
crashed worker's lease reclaimed at `locked_until`. `create_app(require_durable_jobs=True)` now
accepts the marked queue where it refuses the in-process default. The capability is run through the
full `terp.arch` harness like an app (its only opt-outs are governed, budgeted framework-infra
markers) and is under the 100% gate; **no `terp.core` change was needed** (the boot marker,
`run_job`, and the write-scope primitives already existed), so the vendored mirror is untouched. The
broker engine adapters, the sync capability, and scheduler / workflow adapters stay deferred to later
ADRs; the example app is untouched and its budget stays `{}`.

Most recently, the **first engine adapter (ADR 0046)** lands the async/jobs design's Phase 3 —
the proof the jobs seam is genuinely **engine-agnostic**. The opt-in **`terp-cap-jobs-celery`**
library capability (depends only on `terp-core` + `celery`; no entry points, no tables) is a thin
durable `JobQueue` over Celery: **`CeleryJobQueue.enqueue`** ships the whole envelope as the JSON
`kwargs` of **one** canonical Terp task (`terp.jobs.run`), routed to the `JobDefinition`'s `queue`
hint from the live catalog, and **`register_terp_worker(celery_app)`** registers that task on the
worker — it rebuilds the envelope and runs it through the kernel's context-binding `run_job`, so a
job's writes stay **audited + actor / tenant stamped** under Celery exactly as inline (§7, with the
system-actor fallback), the handler resolved **by name** (a stale envelope ⇒ `JobError`) and the
`RetryPolicy` mapped onto Celery's own retry. One canonical task + name resolution keeps the Celery
registry from drifting against the `JobCatalog`. It marks itself **durable** (a persistent broker
survives a restart), so `create_app(require_durable_jobs=True)` accepts it; `send_task` is **not**
transactional, so the dual-write-safe path stays `OutboxJobQueue` + a relay (documented). Shipped
**alongside** it is the 32nd universal rule, **`no_adhoc_background_runtime`** — app modules may not
import a background engine (`celery` / `azure.servicebus` / `redis` / `apscheduler`) or a raw
`threading` / `multiprocessing` execution construct; a pure sync primitive (`from threading import
RLock`) stays allowed, and the adapter reaches Celery under governed, budgeted markers. **No
`terp.core` change** (the boot marker, `run_job`, and context binding already existed), so the
vendored mirror is untouched; the engine adapter wraps a heavy broker lib, so — like the design's
§16 broker adapters — it ships its own suite (run in a broker-free Celery mode proving the
in-process → Celery swap with zero domain change) and is the one cap omitted from the `--cov=terp`
gate. The sync capability stays deferred; the example budget stays `{}`.

Most recently, the **scheduler seam (ADR 0047)** lands the typed scheduling port the design's
§11 calls for — the prerequisite both scheduler adapters and `terp-cap-sync`'s schedule build on.
`terp.core.scheduling` adds **`ScheduleDefinition`** (a dotted name + a typed `JobDefinition` +
an opaque `cron` + an optional `payload_factory`), a **`ScheduleCatalog`** (indexed, dup-rejecting,
with `missing_jobs` boot-validating each schedule's job against the `JobCatalog`), the
**`Scheduler` ABC** (`register` / `register_all` — the one method an engine adapter fills), and
**`trigger_schedule`** (fires a schedule by **enqueuing its job through the typed chokepoint**, so
it flows through the active `JobQueue` and the context-binding runner; a user-less scheduled job
runs as the configured system actor, its writes audited + stamped). `ControlPlane.schedules` +
`create_app` boot-validation refuse a schedule that enqueues an undeclared / shadowed job. The
safe default is the external trigger (any cron fires it), so a scheduled job works with zero
scheduler infra; no module-authored schedule string exists, so the second layer is the boot check
+ the kernel gate (`test_scheduling.py`), not an AST rule. The vendored core mirror is refreshed
byte-exact and `terp.core` stays at 100% coverage. The scheduler **engine adapters** then shipped
(ADR 0048): `terp-cap-scheduler-apscheduler` (an in-process `BackgroundScheduler`) and
`terp-cap-scheduler-celery-beat` (a `beat_schedule` of tick tasks), each firing a schedule through
`trigger_schedule` so the same schedule runs identically whichever engine is wired — library caps
that import their engine behind the seam under a governed marker, with their own broker-free suite
(omitted from `--cov=terp`, like the Celery job adapter). The **`terp jobs scheduler` CLI**
entrypoint then shipped (ADR 0049) — the scheduler-process daemon (`register_all` + a blocking
APScheduler), sibling to `terp jobs run` / `worker`, injectable so it stays 100%-covered without
entering the blocking loop. The example app is untouched, budget `{}`.

Most recently, **`terp-cap-sync` (ADR 0050)** lands the async design's capstone — the "sync last"
consumer capability that proves the seams carry real weight — built entirely on the shipped ports
(jobs / outbox / scheduler) with **no** new `terp.core` surface and no engine. An app implements
one **`SyncSource`** per entity type (`pull` reads System B *inside the job handler*, post-commit,
never an `_after_write` dual-write; `apply` upserts the local row through an **audited
`BaseService`**) and registers it; everything else is the framework's. **`SyncService`** (a
`BaseService[SyncMapping]`) reconciles a page against the **`SyncMapping`** identity ledger (unique
from both sides — the at-least-once idempotency key), creating / updating / skipping each row by
checksum, recording per-run aggregates + a resume cursor on **`SyncRun`** and one append-only
**`SyncRecordLog`** line per record (the audit-style immutable log). A per-record failure is logged
(`ACTION_FAILED`) without aborting the run; a pull failure closes the run `failed` and re-raises so
the outbox retries the whole job idempotently. **`SYNC_PULL` / `SYNC_PUSH`** are declared on the
module (`ModuleSpec.jobs`); **`sync_pull_schedule`** drops a typed `ScheduleDefinition` into a
`ScheduleCatalog`; the admin-only router exposes runs / logs / mappings **read-only** (all
mutations go through the jobs). Like `identity` it is a **library cap** — a `terp.migrations`
history but **no** `terp.capabilities` auto-discovery (a sync does nothing without a registered
source), so the app mounts it explicitly; the example app + its budget `{}` and the frontend
OpenAPI contract are untouched. Held to the full **100%** gate (`test_sync.py`) under its ratcheted
budget (the three append-only-log markers, like the audit sink); migration conformance round-trips
the `sync_mapping` / `sync_run` / `sync_record_log` tables. This completes the async/jobs roadmap:
ports first (jobs 0043, outbox 0045, scheduler 0047), engines as adapters (0046, 0048/0049), sync
last (0050).

Most recently, **secrets sealing (ADR 0055)** carves the design's §5.4 subsystem into
`terp.core.secrets`: `mask_config` (a constant, oracle-free `"****"` — the only
module-facing view of a sealed value), `encrypt_config` (the portable, versioned
`enc:v1:` format; Fernet keyed from `SECRET_KEY` via a domain-separated HKDF), and the
fail-closed `decrypt_config` chokepoint — the composition root registers **exactly one**
call site per process (`register_decrypt_call_site`; a second registration raises), and a
decrypt from anywhere else, with no site registered, on a non-sealed value, or with a
token that no longer authenticates raises the typed `SecretsError`. The build-time pair
is the 33rd universal rule, `no_adhoc_config_decrypt` — a `decrypt_config(...)` call in
app code is flagged, so the one sanctioned site is a justified, budgeted
`# arch-allow-*` marker under the ratchet. The cipher ships as the optional
`terp-core[secrets]` extra (`cryptography>=48.0.1`, lazily imported — the kernel's
default dependency set is unchanged), the kernel gate proves the runtime half in
`test_decrypt_single_call_site` (the design-§5.4 named test), the vendored mirror is
refreshed byte-exact, and the example app + its budget `{}` are untouched.

Most recently, the **base profile closed (ADR 0060)** — `projects` is reclassified as
example module code (business nouns are client modules, never capabilities), so Phase 2's
gate ships without a `terp-cap-projects`; and the first remaining Phase-A checkbox landed:
the **`policy_refs_resolve` arch rule**, the build-time registry-resolution twin of
`ControlPlane.validation_errors` — any authority reference a module traces to
`control_plane/permissions.py` (a module alias, a from-import, or a re-export) must name a
declared registry entry, and importing the registry in an app that declares none is itself
a violation. Precise, never heuristic: references the scan cannot trace to the registry
(kernel defaults such as `Roles.EDITOR`) stay with the boot check.

Most recently, the **copier template's control-plane layout was reconciled** with the
locked default (ADR 0002: **top-level `control_plane/`**): the template's authority
surface moves from `app/control_plane/` to a top-level `control_plane/` package —
imports, hatch packaging, the Dockerfile, and the compose watch sync follow — so a
scaffolded app matches the example app and the CLI default
(`control_plane:control_plane`), `terp inspect control-plane` works out of the box, and
the `policy_refs_resolve` arch rule (which resolves the registry at the app root's
sibling `control_plane/permissions.py`) covers template-derived apps instead of
silently skipping them.

Most recently, **Phase 8 closed** with the **second divergent row-scope consumer
(ADR 0061)**: the example app's `journals` module registers a **visibility-based read
predicate** on the ADR 0017 registry — a `visibility` column (`shared` default /
owner-only `private`) whose consumer-registered predicate appends
`shared OR owner_id == current_actor_id()` to every `Journal` read, fail closed (an
unknown value or an anonymous caller never widens reads). `terp.core` gained only the
tiny `current_actor_id()` read seam (the read half of `bind_audit_actor`); no strategy
code entered the kernel. Two consumers with nothing in common — tenancy's
ambient-claim partition and this caller-keyed row opt-out — now compose on the same
seam, validating core's tenancy-agnosticism. The predicate's `owner_id` comparison is
the example app's one governed opt-out (`arch-allow-no-manual-ownership-checks`,
budget `{}` → 1), dogfooding the escape-hatch ratchet on the real app.

Most recently, **three of ADR 0084's six `deferred` runtime classifications closed**:
the boot route-scan seam `_validate_router_response_models` (the ADR 0020 table-model
guard) now also refuses, per composed route (decorator, imperative `add_api_route`,
and nested included routers alike), a content route with **no declared
`response_model`** (`_validate_routes_declare_response_model`; no-body 204/205/304
statuses and `Response`-subclass-annotated non-content routes such as the files
download stay exempt), a response DTO carrying a **credential-shaped field**
(`_validate_schemas_exclude_sensitive_fields`; the same underscore-delimited word
match + `token_version`/`version`/trailing-`token` exclusions as the arch rule, with
framework-vetted `terp.*` DTOs exempt — the auth `AccessToken` keeps its budgeted
build-time marker), and a **bare `list[...]`/`Sequence[...]` list envelope** instead
of `Page[T]` (`_validate_list_routes_paginate`). Each `BootError` names the violated
Terp Standard rule and route. `terp.core` is layer 0 and cannot import the harness, so
the mirrored constants are parity-locked against `terp.arch` by
`test_runtime_constants_match_the_arch_harness`
(`tests/architecture/test_response_model_guard.py`). The terp-spec catalog entries
`backend/routes_declare_response_model`, `backend/schemas_exclude_sensitive_fields`,
and `backend/list_routes_paginate` **flipped `runtime.applicability` from `deferred`
to `required` in spec v0.6.0** (each declaring its `terp.core` `_validate_*` runtime
enforcement entry, per ADR 0084); the framework adopted the release by bumping both
spec pins to `v0.6.0` together (ADR 0082) and dropping the one-release
`LEGACY_MARKER_ALIASES` + the version-gated parity skips. That leaves
`no_adhoc_middleware`, `no_dependency_overrides`, and `tables_have_migrations` as the
remaining deferrals.

Most recently, **the last three ADR 0084 `deferred` classifications gained their
fail-closed runtime halves** (branch `runtime-deferrals`). `no_adhoc_middleware`:
the composition freeze (`_freeze_app_route_registration`) now also refuses
`add_middleware(...)` and the `@app.middleware(...)` decorator on the composed app
(`_freeze_app_middleware_registration` in `terp.core.app`; `create_app`'s
`middleware=[...]` parameter stays the one sanctioned seam).
`no_dependency_overrides`: outside the `local` environment the composed app's
`dependency_overrides` is replaced by a refusing mapping
(`_freeze_dependency_overrides` / `_FrozenDependencyOverrides` — reads keep serving,
every mutating spelling raises `BootError`); local dev/test compositions keep the
writable map, preserving the sanctioned test-only override seam the framework's own
suites use. `tables_have_migrations`: the boot guard now refuses the standalone
missing-history case — `assert_no_missing_histories` (called first by
`assert_migrations_current`, exported from `terp.migrations`) raises the new
`MissingMigrationsError` when a *declared* tree (capability entry point or app
module) ships a models module whose import path owns mapped tables but has no
revision file, scoped so a fixture model outside every declared tree can never
false-positive (the FK-scoped homeless-table check at `terp migrate make` is
unchanged). Proven by the composition-freeze tests in
`tests/architecture/test_core_app.py` and the missing-history tests in
`tests/architecture/test_migrations_runtime.py`. The catalog flips
(`runtime.applicability` `deferred` → `required`, each entry naming its runtime
enforcement ref above) ship separately in the next terp-spec release; until the pin
bump the three entries' `tracking` notes point here — **runtime halves: done,
catalog flip: pending the spec release**.

Legend: ✅ done · 🔄 in progress · ⬜ not started · 🟡 partial

---

## Active execution track

Authoritative design refinement:
[docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

Accepted decision:
[ADR 0002](decisions/0002-control-plane-and-auditable-module-authority.md).

**Phase A — control-plane spine + centralized permission model** landed (typed
`ControlPlane`, typed `Role` / `Permission`, `Policy` normalization, boot
validation, the first control-plane arch rules, a top-level `control_plane/` in
the example app, and a minimal `terp inspect control-plane` view), followed by
the conformance + 100%-coverage gate (ADR 0003), the typed `Principal` role (ADR
0004), and **Phase C — security middleware + structured logging (ADR 0005)**,
hardened (ADR 0006), **Phase D — audit auto-emit (ADR 0007)**, and the **Phase D
event bus (ADR 0008)**. The next track is **Phase B** (permission-model depth) or
the **`terp-cap-sync`** consumer capability, on top of the durable outbox (ADR 0045), the first
engine adapter **`terp-cap-jobs-celery` (ADR 0046)**, and the scheduler seam + adapters
(ADR 0047 / 0048) now shipped.

**Locked defaults:** typed Python `control_plane/` plus `terp.toml` for pure data;
the current three-tier ladder as the default permission model; top-level
`control_plane/`. Security middleware + structured logging (the post-A/B track) is
now shipped (ADR 0005).

**Documentation rule for this effort:** every implementation slice must update
this status file before the turn ends, and every accepted design decision must be
recorded in `docs/decisions/`, so progress survives chat loss.

### Phase A progress — 2026-06-24

- [x] Accepted and recorded
  [ADR 0002](decisions/0002-control-plane-and-auditable-module-authority.md):
  control-plane package, typed object references, explicit security opt-outs,
  top-level `control_plane/`, and security middleware/logging as the next track
  after A/B.
- [x] Added `terp.core.permissions`: typed `Role`, `Permission`,
  `AuthorizationRequirement`, and `PermissionModel` with the existing
  `viewer < editor < admin` ladder as the compatibility default.
- [x] Added `terp.core.ControlPlane` and boot validation in `create_app(...,
  control_plane=...)` so module policy references fail closed if undeclared.
- [x] Generalized `Policy` so it accepts either typed roles/permissions or the
  legacy `Roles` enum, while preserving `Policy.default()` and existing callers.
- [x] Added the example app's top-level `control_plane/` package and wired it
  into `apps/example/app/main.py`.
- [x] Added the first Phase-A arch rule,
  `no_adhoc_permission_literals`, catching bare authority strings in
  `Policy(...)` and `require_permission(...)` app references.
- [x] Added minimal `terp inspect control-plane`, including roles, permissions,
  and provided module policy requirements.
- [x] Full gate green: `92 passed in 1.39s`.

Remaining Phase A work:

- [x] Add the build-time registry-resolution check for typed policy references —
  shipped as the `policy_refs_resolve` arch rule: any authority reference that traces
  to `control_plane/permissions.py` must name a declared entry (the static twin of
  `ControlPlane.validation_errors`).
- [ ] Expand the control-plane import-boundary rule beyond bare authz strings.
- [ ] Move module `emits` / `subscribes` / `realtime` declarations from inert
  string fields to typed object references as those registries land.
- [ ] Grow `terp inspect control-plane` into the full remote-audit authority map
  (warnings, opt-out ledger, `--json`, diff view) in Phase H.

### Conformance + coverage gate — 2026-06-24 (ADR 0003)

The structured, enforced suite that catches drift / bad usage:

- [x] **Framework-conformance scanner** — new `terp-arch` rules
  `table_models_use_base_table` (every `table=True` model inherits `BaseTable`)
  and `no_app_instantiation` (no hand-built `FastAPI()` in app code). They join
  the Phase-A `no_adhoc_permission_literals` and the original seven.
- [x] **Harness self-completeness meta-test** — every `check_*` rule must be wired
  into `_ALL_RULES` *and* have a `test_<rule>`; the harness cannot silently become
  incomplete.
- [x] **100% framework line-coverage gate** — `pytest --cov=terp` with
  `fail_under = 100`; unexercised `terp.*` code fails the build. Branch coverage
  is 99% (3 documented defensive partials) — tightening tracked, not blocking.
- [x] **Authority-map visualization** — `terp inspect control-plane --format
  mermaid` renders the permission model + module policies as a diagram.
- [x] **CI** — `.github/workflows/ci.yml` runs `uv run pytest --cov=terp` on every
  push / PR.
- [x] Full gate: **141 passed, 100% line coverage**.

### Phase C — security middleware + structured logging — 2026-06-24 (ADR 0005)

The security substrate is now a central control-plane registry installed by
`create_app` (design §5 Phase C). See
[ADR 0005](decisions/0005-security-middleware-and-structured-logging.md).

- [x] **`SecurityConfig` registry** on `ControlPlane.security` (defaulted, so
  existing apps boot unchanged): `SecurityHeaders`
  (HSTS/X-Frame/X-Content-Type/Referrer/Permissions-Policy/CSP), `CorsPolicy`
  (**deny-by-default**), `RateLimit`, `max_request_bytes`, `request_id_header`.
- [x] **Middleware stack** installed by `create_app` (outer→inner: CORS ·
  request-id · security-headers · rate-limit · request-size-limit), all wired from
  the one declaration. Rate-limit state is per-app-instance.
- [x] **Structured logging** — `request_id` context var (set by the request-id
  middleware), a `RedactingFilter` (scrubs `Authorization`/`Bearer`/secret-like
  keys), and a JSON `StructuredFormatter`; `configure_logging()` is idempotent and
  called once at boot.
- [x] **Production fail-fast extended** — `create_app` raises `BootError` under
  `ENVIRONMENT == "production"` on unset/`"*"` CORS, a disabled rate limit, or
  audit enabled without a **marked** `DurableAuditSink` (ADR 0014; pass the audit
  capability's `persist_audit` sink or use `AuditPolicy.disabled(reason=...)`) —
  complements the existing `Settings` guardrails.
- [x] **Two-layer terp-arch rules** — `no_adhoc_middleware` (bans
  `add_middleware` / `BaseHTTPMiddleware` in modules) and `no_adhoc_logging_config`
  (bans `basicConfig` / `dictConfig` / `fileConfig`); both registered in
  `_ALL_RULES`, tested, and the meta-test enforces the pairing.
- [x] **Example app** declares `control_plane/security.py`
  (`CorsPolicy.disabled(reason=...)`) and dogfoods both rules clean; escape-hatch
  budget stays `{}`.
- [x] Full gate: **179 passed, 100% line coverage**.

### Phase C hardening — 2026-06-24 (ADR 0006)

Review of the shipped Phase C slice surfaced four Tier-A correctness defects, all
fixed before moving on (they *complete* controls, not add features). The
cross-cutting controls roadmap + the Tier A/B/C opinionation policy (the
"quadruple" rule) are recorded in
[IMPLEMENTATION_PLAN §10](IMPLEMENTATION_PLAN.md) and
[ADR 0006](decisions/0006-cross-cutting-controls-and-opinionation-policy.md).

- [x] **Logging redaction** now installed on every **handler** (not only the root
  logger), closing a child-logger bypass; sensitive `extra=` fields are redacted.
- [x] **CORS preflight** now carries request-id + security headers (those
  middlewares wrap CORS).
- [x] **`no_adhoc_middleware`** also catches the `@app.middleware("http")`
  decorator form.
- [x] **Catch-all exception handler** renders a generic `internal_error` 500
  envelope (logged with the request id); no stack-trace leak, uniform contract.
- [x] Full gate: **182 passed, 100% line coverage**.

### Phase D — audit auto-emit — 2026-06-24 (ADR 0007)

The highest-value Tier-A gap (ADR 0006): a mutation audit trail that is
**unbypassable** and **wiring-free**, emitted from the single `BaseService` write
chokepoint. See
[ADR 0007](decisions/0007-audit-auto-emit-and-the-audit-seam.md).

- [x] **`AuditPolicy` registry** on `ControlPlane.audit` (safe default: audit
  **every** mutation; central redaction via `redact_keys`; `retention_days` knob;
  explicit `AuditPolicy.disabled(reason=...)` opt-out) — a Tier-A control that is
  never silently absent.
- [x] **Fail-closed auto-emit** — `BaseService.create` / `update` / `delete` route
  through one `_save` / `_remove` primitive that calls `emit_audit(...)` **inside
  the write's transaction**, so the audit row commits atomically and a failing sink
  aborts the mutation. Zero per-module code; a bespoke mutation (the `tasks`
  soft-delete) re-uses `_save` and is audited too.
- [x] **Core seam + capability sink (layering)** — `terp.core.audit` defines the
  seam (`AuditAction` / `AuditRecord` / `AuditPolicy` / `audit_actor_ctx` /
  `emit_audit`) with a **log-only default sink**; the opt-in **`terp-cap-audit`**
  supplies the durable append-only `AuditEvent` table + `persist_audit` sink + a
  self-registering, admin-only read router. Wired in one line:
  `create_app(..., audit_sink=persist_audit)`. The actor is resolved through the
  `get_principal` seam (an async binder `create_app` mounts on every router).
- [x] **Two-layer `terp.arch` rule** — `mutations_emit_audit` bans raw
  `session.add` / `delete` / `merge` / `commit` in modules (persistence must go
  through the audited chokepoint); registered in `_ALL_RULES`, tested, and the
  meta-test enforces the pairing.
- [x] **Event bus split out** — audit-first; the event bus (and typed
  `emits` / `subscribes`) remains future work and audit does not depend on it.
- [x] **Example app** dogfoods the trail clean (`control_plane/audit.py` declares
  the policy; `build()` installs the sink); escape-hatch budget stays `{}`.
- [x] Full gate: **200 passed, 100% line coverage**.

### Phase D — event bus (typed `EventCatalog` + NO-DRIFT `emit`) — 2026-06-24 (ADR 0008)

The open Phase-D subsystem (ADR 0007 split it out of audit): the event bus as an
**optional product feature** whose only guarantee is **no drift** — every emitted
or subscribed event is a registered, typed object, never a bare string. See
[ADR 0008](decisions/0008-event-bus-catalog-and-typed-emit.md).

- [x] **`EventCatalog` registry** on `ControlPlane.events` (default **empty** = the
  bus is *inactive*, a silently-absent product feature — contrast the always-on
  Tier-A `AuditPolicy`). A typed `EventDefinition` is a dotted `name` + a
  `payload_schema` + an `EventVisibility` (`PUBLIC` / `INTERNAL` / `RESTRICTED`);
  duplicate names are rejected.
- [x] **Fail-closed `emit`** — `terp.core.emit(session, *, event, payload=None)`
  accepts **only** an `EventDefinition`, resolves the **canonical** catalog entry
  and rejects an unknown name **or** a same-name *shadow* (different schema /
  visibility) (`EventError`), validates the payload against the canonical schema,
  builds a typed `EventEnvelope`, and hands it to the active dispatcher. `create_app`
  boot-validates every `ModuleSpec.emits` / `subscribes` against the catalog by
  value (the static half).
- [x] **Core seam + capability dispatcher (layering)** — `terp.core.events` defines
  the seam with a **no-op default dispatcher** (an app with a catalog but no bus
  capability still validates emits; the event goes nowhere). The opt-in
  **`terp-cap-eventbus`** (a *library* cap — no entry point, no router, no tables)
  supplies the in-process handler registry (`subscribe`) + `dispatch_in_process`,
  wired in one line: `create_app(..., event_dispatcher=dispatch_in_process)`.
- [x] **Two-layer `terp.arch` rule** — `events_reference_catalog` forbids a bare
  string (or inline `EventDefinition(...)`) wherever an event is named (`emit` /
  `subscribe` / `ModuleSpec(emits=/subscribes=)`); registered in `_ALL_RULES`,
  tested, and the meta-test enforces the pairing.
- [x] **`ModuleSpec.emits` / `subscribes` are now typed** (replacing the inert
  bare-string `events` field) — typed catalog references validated at boot.
- [x] **Durable outbox split out** — the catalog + typed emit + in-process dispatch
  land first; the durable transactional outbox + worker is a later, drop-in
  dispatcher swap (no `emit` call-site change).
- [x] **Example app** dogfoods the bus clean (`control_plane/events.py` declares
  `NOTE_CREATED`; `notes` emits it from a `BaseService._after_write` hook **inside
  the write's transaction**; `tasks` subscribes through the central catalog);
  escape-hatch budget stays `{}`.
- [x] Full gate: **230 passed, 100% line coverage**.

### Known limitations / genericness gaps (reviewed 2026-06-24)

Honest accounting of where "any backend / any company" is **not yet** fully true.
None are bugs; all are tracked design gaps.

- **Role model — now agnostic at the framework level (ADR 0004).** `Principal.role`
  is a typed `Role` (name + rank) and the JWT carries name + rank, so a consumer
  can declare any role model in its control plane and issue principals bearing
  those roles; the guard enforces by rank. The legacy `Roles` (`viewer/editor/
  admin`) stays as the default + back-compat (normalized via `as_role`). Remaining
  nuances: `Policy.default()` / `tiers()` still reference the default tier *names*
  (rename them and you must declare your own policies), and the bundled
  `terp-cap-identity` store still persists the default `Roles` model (bring your
  own `authenticate` for a custom role store).
- **Named-permission policy requirements are enforced as a real per-subject grant
  (ADR 0016).** `Policy(write=PERM)` now requires the caller to clear `PERM.min_role`
  as a rank *floor* **and** hold the granted permission, checked through the injected
  `permission_enforcer` seam (the access capability's `enforce_permission`); boot
  fails closed if a permission policy has no enforcer, so a permission is never
  degraded to a role tier. `access.require_permission` remains for route-level checks
  layered on top.
- **`Policy.read_role` / `write_role` were retired (ADR 0018).** Enforcement and the
  CLI authority map use the typed `read_requirement` / `write_requirement`; the
  vestigial `Roles` projection (zero production readers) and its `_legacy_role` helper
  were removed. The `read_role=` / `write_role=` constructor aliases remain (they
  normalize into the requirements, like `read=` / `write=`).
- **`ModuleSpec.services` is inert** (ADR D3) — intentionally unwired until a DI
  consumer exists, to avoid premature abstraction. `emits` / `subscribes` are now
  **typed `EventDefinition` references** validated at boot (ADR 0008); `events` (the
  old bare-string field) is gone.

Everything else (module slots, persistence/OCC, tenancy via the scope registry, errors,
pagination, config, the harness, the control-plane permission *declaration*) is
generic by construction.

---

## Phase tracker (design §13)

| # | Phase | Status | Notes |
|---|---|---|---|
| 0 | Inventory & triage + public API surface | ✅ | Folded into the design doc (§13) and the decision records. |
| 1 | Carve `terp-core` + `ModuleSpec` + public surface | ✅ | Kernel + `create_app` + `BaseService` shipped (ADR D3–D5). `.pyi` / api-docs generator now shipped via `terp api-docs` (ADR 0039). |
| 2 | Repackage capabilities (entry-point extras) + base profile | ✅ | auth, access, identity, tenancy, users ✅; entry-point discovery ✅. Base profile closed by ADR 0060 (`projects` reclassified as example module code). |
| 3 | Ship `terp-arch`; delegate layering to a tool | ✅ | Harness shipped (full rule set + `requires` boot check + governed escape-hatch budget ratchet + docs-parity test, ADR 0030; universal rule set completed by ADR 0037). Generic CI backstops now layer on top (ADR 0033): ruff bandit `S`, an import-linter `terp.core` layer-0 contract mirroring `test_core_boundary`, plus advisory pip-audit + deptry — CI-only, never replacing `terp-arch`. |
| 4 | Frontend contract + Stack A (React) + conformance | ✅ | `@terp/contract` (base-profile OpenAPI → typed client + design tokens + stack-agnostic manifest/auth types), `@terp/react-core` (Stack A: `TerpProvider` + auth session, app shell + TanStack router adapter + token-styled primitives + capability gates + `useResource` data hooks), `@terp/eslint-boundaries` (fail-closed module-boundary lint), and `@terp/conformance` (Playwright e2e over the Docker workbench). The example app dogfoods all four (notes/tasks/projects/journals modules); the copier template ships them. |
| 5 | Scaffolding: copier template + `terp` CLI | ✅ | `terp new module` (canonical five slots), the copier `template/` (runnable app + base profile), `terp api-docs` (generated `.pyi` + reference), and `terp check` (ADR 0039). |
| 6 | Agent-visibility layer (§10) | ✅ | `vendor/terp-core/` read-only mirror + `test_vendored_core_unmodified` drift gate (ADR 0034). CODEOWNERS deferred; the publish pipeline shipped (lockstep versions + release.yml + template acceptance, ADR 0063). |
| 7 | Packaged migrations (§4.6) | ✅ | Independent per-package Alembic histories + `terp migrate` (incl. stamp/heads/merge, cross-package FK autogenerate, model-drift check) + boot guard (ADR 0027), plus the `tables_have_migrations` arch rule (ADR 0028). The conformance suite now also runs against real PostgreSQL in CI, and production boot refuses an unverified dialect without an explicit acknowledgement (ADR 0069). Deployments can opt into the per-module schema layout (`DB_SCHEMA_LAYOUT=per-module` + `terp migrate adopt-schemas`, `no_manual_table_schema` rule; ADR 0070) and split privileges with a least-privilege runtime role (`terp migrate grant-runtime`; ADR 0071). Offline `--sql` deferred. |
| 8 | Dogfood: example app + 2nd divergent tenancy strategy | ✅ | Visibility-based read scope on `journals` (ADR 0061): a consumer-registered ADR 0017 predicate (`shared` / owner-only `private`) composing beside the tenant partition (`projects`) — two divergent strategies on one kernel seam validate core's tenancy-agnosticism. |
| 9 | Stack B (Svelte) + release v0.1 | ⬜ | Conformance-driven; needs only the contract. |

---

## Backend capabilities

Base profile (§13 Phase 2) = core + **auth** + **access** + **identity** + **users** (ADR 0060
removed `projects`: business nouns are client modules, never capabilities).

- [x] **auth** — `terp-cap-auth` (Argon2 + HS256 JWT + `get_principal`; a revocable
  provider re-checking `is_active` + a per-user token epoch every request, a per-account
  login lockout, and `/auth/login` + `/auth/logout`, ADR 0031) — ADR D6
- [x] **identity** — `terp-cap-identity` (persisted `User` + auth-only
  `authenticate`; now a **library** capability with **no mutation surface** — the
  admin surface moved to `users`, ADR 0013) — ADR D7
- [x] **tenancy** — `terp-cap-tenancy` (reads scoped by a **registered row predicate** (ADR 0017); `TenantScopedService` stamps `tenant_id` on create through the audited chokepoint; `TenantMiddleware` binds the JWT `tenant` claim per request) — ADR D8, D11
- [x] **access** — `terp-cap-access` (RBAC permission grants + fail-closed `require_permission`; admin grants router via discovery; `grant`/`revoke` now audited via the chokepoint, ADR 0014) — ADR D12 · *base profile*
- [x] **users** — `terp-cap-users` (admin management over identity's `User`:
  provision / edit (OCC) / deactivate / reactivate / reset-password, admin-only +
  audited; deactivate-over-delete) — ADR 0013 · *base profile*
- [x] **groups** — `terp-cap-groups` (admin-managed user groups that **bundle
  permissions**: `user_group` / `user_group_member` + audited membership CRUD at
  `/api/v1/groups`; granting to a group is an ordinary access grant naming the
  group's id, made effective for members by the access **subject-expansion seam**;
  deleting a group cascades to memberships + grants atomically; flat, role-free)
  — ADR 0074 · *base profile*
- [x] **projects** — resolved without a package (ADR 0060): `projects` is the example
  app's `build_crud_router` + tenancy dogfood **module**, the canonical proof that
  business nouns are client modules; no `terp-cap-projects` ships
- [x] **files** — pluggable storage (`terp-cap-files`): **streamed** file-like
  `StorageBackend` port (`put`/`open`, no whole-file buffering — ADR 0066), size-capped
  (25 MiB default, composition-root-retunable, enforced mid-stream + partial-blob
  compensation), SHA-256-derived, owner-scoped upload/download, with storage profiles +
  the typed `FileReference` seam; its `ModuleSpec` declares a per-module request-size
  allowance so the 25 MiB cap works without widening the global 1 MiB request cap
  (ADR 0067), and a deployment can narrow uploads to a content-type allowlist enforced
  in the service chokepoint (typed 415 — ADR 0068) — ADR 0056 / 0057 / 0066 / 0067 / 0068
- [x] **audit** — append-only audit log + auto-emit from the `BaseService`
  chokepoint (`terp-cap-audit`) — ADR 0007
- [x] **eventbus** — typed `EventCatalog` + NO-DRIFT `emit` + in-process handler
  registry, plus the declarative `EventEmittingService` / `LifecycleEventMap`
  authoring mixin (`terp-cap-eventbus`, a library cap) — ADR 0008 / ADR 0009.
  Durable outbox shipped (ADR 0045).
- [x] **outbox** — `terp-cap-outbox` (a library cap): the durable, transactional,
  leased post-commit delivery for **both** jobs and events — an append-only
  `outbox_message` table (own Alembic history), a marked-durable `OutboxJobQueue` +
  `outbox_event_dispatcher` that ride the business write's audited unit (atomic, no
  dual-write), and a retrying / dead-lettering `OutboxWorker` (`terp jobs worker`,
  at-least-once) — ADR 0045
- [x] **webhooks** — `terp-cap-webhooks`: reliable, **signed**, **SSRF-guarded**
  outbound webhooks built only on the shipped ports. An owner-scoped
  (`OwnedMixin`) `WebhookSubscription` (admin router, the signing `secret` never
  serialized) + an append-only `WebhookDelivery` log; a `WEBHOOK_DELIVER` job whose
  handler signs (HMAC-SHA256), re-checks the SSRF denylist, POSTs with a strict
  timeout + no redirects, and lets failures retry / dead-letter on the outbox; an
  `@subscribe` trigger that enqueues atomically with the business write (no
  dual-write) via the new eventbus `current_event_session()` seam. `httpx` is a
  dependency of this cap only — ADR 0051

---

## Core substrate still to carve

Core substrate not yet carved into `terp.core`:

- [x] **Middleware** — security headers, rate-limit, request-id, request-size-limit, deny-by-default CORS (ADR 0005, `SecurityConfig` + `create_app` install). CSRF is intentionally out of scope (Terp authenticates via Bearer tokens, not cookies).
- [x] **Logging / telemetry** — structured logging + request-id context var + PII redaction (`terp.core.logging`, ADR 0005). OTel wiring remains deferred.
- [x] **Secrets sealing** — `encrypt_config` / `mask_config` / `decrypt_config` (single
  decrypt call-site, §5.4) — shipped (ADR 0055): `terp.core.secrets` + the
  `no_adhoc_config_decrypt` rule; the cipher is the optional `terp-core[secrets]` extra
- [ ] **`AddressMixin`** as an opt-in value-object mixin (not a core default)
- 🟡 **Security primitives** — Argon2 + JWT live in `terp-cap-auth`; decide what (if anything) belongs in core

---

## Enforcement harness (`terp-arch`)

Shipped — fail-closed build-time rules, each paired with a runtime control:
`no_internal_imports`, `no_cross_module_imports`, `modules_declare_policy`,
`no_adhoc_permission_literals`, `mutations_require_write_role`,
`public_modules_are_read_only`, `routes_declare_response_model`,
`response_model_not_table_model`, `list_routes_paginate`,
`no_raw_session_construction`, `no_raw_connection_access`, `mutations_emit_audit`,
`events_reference_catalog`, `input_str_fields_have_max_length`,
`input_schemas_exclude_managed_columns`,
`tenant_scoped_models_use_scoped_service`, `no_manual_scope_filtering`,
`base_query_not_overridden`, `reads_use_base_query`,
`no_manual_actor_stamping`,
`no_manual_ownership_checks`,
`table_models_use_base_table`, `tables_have_migrations`,
`safe_methods_are_read_only`,
`no_app_instantiation`, `no_adhoc_middleware`, `no_adhoc_logging_config`,
`no_adhoc_config_decrypt` — plus
`check_app` / `assert_app_clean`, the self-completeness meta-test, and boot-time
`ModuleSpec.requires` validation.

Governed opt-out shipped (§8): a justified `# arch-allow-<rule>: <reason>` comment
suppresses a single violation (a reason-less one fails closed), and
`check_escape_hatch_budget` ratchets the `# arch-allow-*` counts against a
checked-in JSON budget — they must match exactly, so a new opt-out needs a
justified budget bump and a removed one must be locked in by lowering it.
`assert_app_clean` refuses to pass an app that uses any marker without a budget.

**Adversarial-review hardening (ADR 0014):** the harness now **also scans every
capability package** (not just `app/`), so a capability can no longer bypass the
audited chokepoint unseen — the three legitimate framework primitives (the audit
sink's raw write, the append-only `AuditEvent` table, the central tenant
predicate) carry justified `# arch-allow-*` markers under per-capability budgets.
`mutations_emit_audit` was strengthened (bulk/flush verbs, inline and precomputed
DML via `execute` / `exec`, `text('SELECT ...')` read false-positives avoided, and
function-scoped `Session` / `SessionDep` receivers — renaming the variable no
longer evades it), and `no_cross_module_imports` now resolves **relative** imports
including package-alias forms before matching.

**Runtime write-guarded session (ADR 0015):** `SessionDep` now hands out a
`WriteGuardedSession` whose `add` / `add_all` / `delete` / `merge` / `commit` /
`bulk_*` / DML `execute` / `exec` raise `UnauditedWriteError` unless they run
inside the `BaseService` `_save` / `_remove` write scope (`allow_session_writes`).
This is the **structural primary layer** for the audited-write guarantee — a write
that skips the chokepoint fails closed at runtime whatever the session variable is
named or which package it lives in — with the build-time `mutations_emit_audit`
rule kept as the second (early-warning) layer. The scope opener lives under
`terp.core._internal`, so a module cannot import it to bypass the guard
(`no_internal_imports` is the layer guarding the guard).

Remaining:

- [x] Delegate generic layering to a tool + wire deptry / pip-audit — import-linter
  `terp.core` layer-0 contract (mirrors `test_core_boundary`) plus advisory deptry /
  pip-audit in the CI-only `generic-checks` job (ADR 0033)
- [x] Delegate baseline security lints (`eval` / `exec` / raw-SQL / bind-all /
  unsafe-deserialize / shell-true) to **ruff `S`** (bandit) repo-wide, keeping the
  bespoke rules as the second layer (ADR 0033)
- [x] Add the remaining secure-by-default rules:
  `mutations_require_write_role`, `schemas_exclude_sensitive_fields`,
  `canonical_module_shape` (`models` / `schemas` / `service` / `router` present),
  `session_imported_from_sqlmodel` — shipped (ADR 0037; each a fail-closed AST rule +
  meta-test, surfaced in the generated `terp guide rules`)
- [x] Docs-parity test (rules ↔ documented invariants) — shipped (ADR 0030: generated rules surface + parity meta-tests)
- [x] `test_vendored_core_unmodified` (Phase 6) — shipped (ADR 0034: `vendor/terp-core/` read-only mirror + byte-match drift gate)
- [ ] *(optional)* ratcheting file line-budget guard — considered after the
  `rules.py` → `rules/` split (the framework's one 963-line outlier, now ≤166);
  deferred because a blunt cap fights the intentionally cohesive registries

---

## Deferred backlog (recorded, intentionally not built)

- [x] `ModuleSpec.emits` / `subscribes` wiring — typed `EventDefinition` references
  validated against the `EventCatalog` at boot (ADR 0008). `services` stays inert
  until a DI consumer exists.
- [x] `BaseService` commit-ownership — chokepoint owns one re-entrant commit; nested
  writes join the same atomic, audited unit (ADR 0038)
- [x] auth: **token revocation (per-user epoch) + mid-session `is_active` re-check +
  per-account login lockout** — shipped (ADR 0031). **Refresh-token rotation** (httpOnly
  cookie, single-use rotation, reuse-detection, reload-surviving React session) shipped in
  ADR 0054. **Pluggable SSO (OIDC)** shipped in ADR 0058 (`terp-cap-oidc`: code flow +
  PKCE, federated `(issuer, subject)` linking, JIT provisioning off by default). Still
  deferred: a `jti` deny-list, SAML, and RP-initiated / back-channel logout. The shared
  multi-instance throttle store landed (ADR 0036).
- [ ] tenancy: raw-query (session-level) isolation — the `TenantMiddleware` + JWT `tenant` claim shipped (D11)
- [ ] `foundation/` default layer — introduce only if a neutral app proves the need
- [x] **`build_crud_router`** — a Level-1 opt-in CRUD-router builder (Tier C,
  ADR 0006 / [IMPLEMENTATION_PLAN §10.2](IMPLEMENTATION_PLAN.md)) returning a native
  `APIRouter`, so a flat module gets identical wired CRUD with no per-module route
  drift and no DSL; the example `projects` module adopts it — **shipped (ADR 0023)**
- [x] **scope-predicate registry** — `terp.core.scoping.register_scope_predicate`
  lets a capability plug its row predicate into core without core importing it;
  `terp-cap-tenancy` now registers its tenant predicate (no `base_query` override),
  composed centrally by `BaseService.base_query` — **shipped (ADR 0017)**
- [x] **durable event outbox** — the transactional outbox + leased retrying worker,
  a drop-in dispatcher swap with no `emit` call-site change (deferred from ADR 0008).
  Unified with the jobs durable queue and **shipped as `terp-cap-outbox` (ADR 0045)**,
  the async/jobs design's Phase 2, on top of the jobs seam (ADR 0043). The broker engine
  adapters + `terp-cap-sync` are the remaining async/jobs ADRs.
- [ ] **adversarial-review follow-ups (ADR 0014, sequenced as their own decisions)** —
  the structural items the review surfaced beyond the hardening already shipped:
  - [x] runtime **write-guarded session** handed out by `SessionDep` — a
    `WriteGuardedSession` whose mutators raise `UnauditedWriteError` outside the
    `_save`/`_remove` write scope (the structural primary layer; the
    `mutations_emit_audit` rule stays the build-time second layer) — **shipped
    (ADR 0015)**
  - [x] **`Permission`-in-`Policy` guard** — a permission requirement is enforced as a
    real per-subject grant (rank floor **and** the grant, via the injected
    `permission_enforcer` seam); `create_app` fails closed at boot when a permission
    policy has no enforcer — never a silent collapse to a rank — **shipped (ADR 0016)**
  - [x] **non-overridable scope predicate** — `base_query` is a central composition
    (soft-delete + registered row predicates + the `business_filters()` hook) and the
    `base_query_not_overridden` rule forbids overriding it, so a `super()`-less
    override cannot drop soft-delete / tenant scope — **shipped (ADR 0017)**
  - [x] **`response_model` must not be a `table=True` model** — a route returning a
    persisted model (directly or via `Page[...]` / `list[...]`) is rejected at boot
    (`create_app` → `BootError`) **and** by the build-time `response_model_not_table_model`
    rule, so e.g. `Page[User]` cannot leak `hashed_password` — **shipped (ADR 0020)**
  - [x] **first-class middleware composition seam** — `create_app(..., middleware=[...])`
    composes capability middleware (e.g. `TenantMiddleware`) through the sanctioned root, so
    the flagship multi-tenant feature is wired in the composition path, not a test-only
    `add_middleware`; `no_adhoc_middleware` stays the build-time pair — **shipped (ADR 0021)**
  - [x] **dogfood: tenant-scoped `projects` module** — the example app ships a tenant-scoped
    `projects` resource (`TenantScopedMixin` + `TenantScopedService`) wired via the middleware
    seam in `main.build()`, with an e2e test proving per-token-tenant isolation over HTTP —
    closes the review §4-Q5 gap (the example app had no tenant-scoped model)
  - [x] **tenant-aware login + custom-role wiring (H7)** — `IdentityService` resolves a user's
    stored rank through the app's `PermissionModel` (a consumer-defined role authenticates instead
    of 500ing), and `build_login_module(..., tenant_resolver=)` signs the `tenant` claim through the
    same seam `TenantMiddleware` reads — **shipped (ADR 0022)**
- [x] **framework self-coverage gap** — closed by framework-owned tests so the
  bundled stack (auth login/logout, users admin, access grants, the audit log) and
  the tenancy middleware reach full `terp.*` coverage from `tests/` **alone**, with
  no `apps/example`. `tests/architecture/test_framework_stack.py` assembles the same
  stack — revocable provider, durable audit sink, permission enforcer,
  `TenantMiddleware` — over an in-memory DB. The example dogfood is now purely
  additive; the `--cov=terp` gate stays defined over the full suite, `fail_under=100`
  unchanged — **shipped (ADR 0035)**
- [x] audit auto-emission (§5.8) — shipped as `terp-cap-audit` + the core seam (ADR 0007)
- [x] **packaged Alembic migrations (Phase 7)** — independent per-package linear
  histories + `terp migrate` (upgrade/downgrade/make/status/check/stamp/heads/merge) +
  a fail-closed pending-migrations boot guard, cross-package FK autogenerate, and a
  reusable model-drift check (ADR 0027)

### Production deployment profile + release pipeline — 2026-07-03 (ADR 0062 / ADR 0063)

Phase G's prod-profile half + the deferred "dist-only publish" item, landed together so
"deployable" is CI-enforced, not aspirational.

- [x] **Production images** — multi-stage `Dockerfile.prod` (wheels-only runtime, non-root,
  no `--reload`, healthcheck) + a `vite build` → non-root nginx frontend image (SPA
  fallback, immutable-asset caching, same-origin `/api` proxy), for the example app AND
  the copier template — ADR 0062.
- [x] **`docker-compose.prod.yml`** — `db → migrate → api + web`, `ENVIRONMENT=production`
  (fail-fast guardrails armed), `:?`-required secrets (no dev fallback), **no seed
  service** (bootstrap via `terp user create`), restart policies — ADR 0062.
- [x] **Two-layer guard** — `tests/architecture/test_prod_profile.py` (structure tests,
  example↔template parity) + `.github/workflows/prod-smoke.yml` (build + boot the prod
  profile in CI: readiness, admin bootstrap, login through nginx, authenticated `/me`,
  `terp seed` refuses production) — ADR 0062.
- [x] **Deployment guide** — `docs/DEPLOYMENT.md` (single-host Compose is the reference
  target; k8s deferred on evidence) — ADR 0062.
- [x] **Lockstep release** — every distribution at one version (`0.1.0`), enforced by
  `tests/architecture/test_release_versions.py`; `CHANGELOG.md`; npm packages flipped
  publishable — ADR 0063.
- [x] **`release.yml`** — on tag `v*`: verify (tag↔version + full gate) → PyPI (trusted
  publishing) + npm (`--provenance`) + GHCR prod images — ADR 0063.
- [x] **Template acceptance CI** — render the copier template, stage local wheels
  (`UV_FIND_LINKS`) + packed npm tarballs, run the generated repo's own gate and frontend
  build **outside the workspace**; its first run caught and fixed a real template bug
  (the scaffolded module shipped no migration) — ADR 0063.

### Data-layer scale decisions — 2026-07-04 (ADR 0064 / ADR 0065)

The two data-layer items the direction & completeness review required to become
conscious decisions, closed together.

- [x] **Keyset (cursor) pagination + opt-in total (review M5)** — `CursorPage[T]` +
  `CursorPaginationDep` (`cursor` / `limit` / `include_total`, same hard caps) and
  `BaseService.list_by_cursor` walking the stable `(created_at, id)` keyset on the
  same non-droppable `base_query()` scope; no `OFFSET` scan, `COUNT(*)` only when
  asked, opaque tamper-checked cursor (a garbled value → typed 400). Purely
  additive: offset `Page[T]` stays the default and every existing endpoint /
  contract is unchanged — ADR 0064.
- [x] **The data layer stays sync (documented)** — one enforced session path (write
  guard, commit-owning chokepoint, row-scope backstop) beats a duplicated async
  control set; the ceiling is pool tuning (ADR 0024) + horizontal workers, slow work
  belongs on the jobs seam, and the revisit trigger is written down — ADR 0065.

### Production-readiness gaps (2026-06-24 direction & completeness review)

Surfaced by the [direction & completeness review](reviews/2026-06-24-direction-and-completeness-review.md)
(production-readiness for a complex, large app); recorded so the roadmap stays
complete. Suggested next sequence (object-level authz now done, ADR 0029):
**jobs/outbox/OTel**.

- [x] **Health / readiness / liveness endpoints** — `create_app` mounts public
  `/health/live` (liveness) + `/health/ready` (DB `SELECT 1`, 200/503) — **shipped (ADR 0024)**.
- [x] **Engine / connection-pool configuration** — `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` /
  `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING` on `Settings`, applied by the
  engine factory to a server DB (SQLite keeps its defaults); statement-timeout now
  shipped: `DB_STATEMENT_TIMEOUT_MS` (default 30s) is applied per pooled Postgres
  connection (`options=-c statement_timeout`), 0 disables it in dev/test only — the
  production guardrail refuses a missing timeout — **shipped (ADR 0024)**.
- [x] **Sync-vs-async DB decision (documented)** — the data layer is sync (`Session`
  per request in the threadpool); decide + document whether to stay sync (with pool
  tuning + limits) or offer an async-session path. **Decided: Terp stays sync
  (ADR 0065)** — one enforced session path (write guard / commit chokepoint /
  row-scope backstop) beats a duplicated async control set; the ceiling is governed
  by pool tuning (ADR 0024) + workers, and slow work belongs on the jobs seam.
- [x] **Object-level / ownership / row authorization seam** — the per-row complement
  to the per-permission gate (ADR 0016); keeps "may this caller edit *this* row" off
  the hand-rolled, scope-droppable path (relates to H2). **Shipped (ADR 0029):**
  `OwnedMixin` + the `terp.core.object_authz` registry + the `BaseService` chokepoint
  write gate + the `no_manual_ownership_checks` rule + the `journals` dogfood. Read
  visibility remains the scope-predicate seam (ADR 0017).
- [🟡] **Background jobs / scheduler** — async work, retries, scheduled tasks (emails,
  exports, webhooks); a capability + a worker entry point. **Phase 1 shipped (ADR 0043):**
  the core job seam — `terp.core.jobs` (typed `JobDefinition` / `JobCatalog` /
  `JobEnvelope` / `JobQueue` + the `InProcessJobQueue` default + fail-closed `enqueue`), the
  `job_runtime` context-binding worker (actor / tenant / request-id re-bind + system-actor
  fallback), `create_app(job_queue=, require_durable_jobs=)` + boot validation, the
  `jobs_reference_catalog` rule, and the `terp jobs run / list` + `terp inspect jobs` CLI.
  **Phase 2 shipped (ADR 0045):** the durable `terp-cap-outbox` (transactional `outbox_message`
  table + leased retrying / dead-lettering `OutboxWorker` + `terp jobs worker` + the
  `require_durable_jobs` boot guard). **Phase 3 shipped (ADR 0046):** the first engine adapter
  `terp-cap-jobs-celery` (`CeleryJobQueue` + `register_terp_worker`, durable-marked, `RetryPolicy`
  → Celery retry, in-process → Celery swap with zero domain change) + the
  `no_adhoc_background_runtime` rule keeping engines out of app code.
  **Scheduler seam shipped (ADR 0047):** the typed `terp.core.scheduling` port
  (`ScheduleDefinition` / `ScheduleCatalog` / `Scheduler` ABC / `trigger_schedule`,
  boot-validated against the `JobCatalog`); the external-trigger default needs no scheduler
  infra. **Scheduler adapters shipped (ADR 0048):** `terp-cap-scheduler-apscheduler` (in-process)
  + `terp-cap-scheduler-celery-beat` (a `beat_schedule` of tick tasks), both firing schedules
  through `trigger_schedule`. **Scheduler CLI shipped (ADR 0049):** `terp jobs scheduler` runs the
  in-process scheduler daemon (sibling to `terp jobs run` / `worker`). Deferred to later ADRs: the
  `terp-cap-sync` consumer capability, the workflow-engine port, and the Azure SB / Redis adapters.
- [x] **Caching seam** — an opt-in cache (e.g. Redis) for hot reads. **Kernel seam
  shipped:** `terp.core.cache` (`CacheStore` port + per-process `InMemoryCacheStore`
  default + `get_cache()` accessor) and `create_app(cache_store=,
  require_shared_cache_store=)` — the boot guard fails closed on an unmarked
  per-instance store when a deployment promises a shared cache
  (`mark_shared_cache_store`), mirroring the throttle-store quadruple (ADR 0036).
  **Redis adapter shipped (ADR 0078):** `terp-cap-redis` provides `RedisCacheStore`.
- [x] **Idempotency keys** for unsafe methods (safe client retries at scale) —
  **shipped (ADR 0077):** an `Idempotency-Key`-carrying unsafe request executes
  once and its response is stored + replayed to a retry of the same key
  (`Idempotency-Replayed: true`); the key is credential-scoped (hashed), a reused
  key for a different request is a typed 422, a concurrent duplicate a typed 409,
  and a claim-time store error fails closed (typed 503 — never a silent double
  execution). The pluggable `IdempotencyStore` port ships the bounded per-process
  default; `create_app(idempotency_store=…, require_shared_idempotency_store=…)`
  is the multi-instance quadruple's boot guard, mirroring the throttle/cache
  stores (ADR 0036). **Redis adapter shipped (ADR 0078):** `terp-cap-redis` provides
  `RedisIdempotencyStore`. Requests without the header are untouched.
- [x] **Keyset / cursor pagination + optional total** — avoid the mandatory exact
  `COUNT(*)` per list on large tables (review M5). **Shipped (ADR 0064):**
  `CursorPage[T]` + `CursorPaginationDep` (opaque, tamper-checked cursor; the
  `COUNT` is opt-in via `include_total`) and `BaseService.list_by_cursor` walking
  the `(created_at, id)` keyset on the same non-droppable `base_query()` row scope;
  offset `Page[T]` stays the default and every existing contract is unchanged.
- [x] **Outbound webhooks / notifications** capability — `terp-cap-webhooks`
  (ADR 0051): signed (HMAC-SHA256), SSRF-guarded, owner-scoped outbound webhooks on
  the jobs/outbox seam; an `@subscribe` trigger enqueues a durable delivery atomically
  with the business write, the outbox worker POSTs it off-request with retry /
  dead-letter, and the signing secret never leaves the API boundary.
- [x] **Distributed rate limit + shared lockout store** — the rate limiter and the
  per-account login throttle keep state behind a pluggable `ThrottleStore` (default
  in-memory; a multi-instance deploy plugs one shared backend), fail-closed, default
  unchanged — **shipped (ADR 0036)**. **Redis adapter shipped (ADR 0078):**
  `terp-cap-redis` provides `RedisThrottleStore`. The last-admin guard's multi-instance shared
  lock (review L3) is closed at the database: `_active_admin_count` selects the active
  admin rows `FOR UPDATE` inside the same transaction as the demotion / deactivation
  write, so concurrent instances serialise on the row locks (pinned by a build-time
  test); the per-process `RLock` remains only as the SQLite dev/test belt, where
  `FOR UPDATE` is a no-op.

### Code-quality audit (2026-06-24)

A code-quality / tech-debt pass (distinct from the feature-completeness review).
**Verdict: the codebase is clean and consistent — no big refactor needed.** No
`TODO`/`FIXME`/`HACK` in source; `# type: ignore` is confined to justified SQLModel
limitations and test spies; packages share a uniform shape and the rules harness was
already split into a cohesive `rules/` package.

- [x] **PEP 561 `py.typed` markers** added to the 5 packages that shipped types without
  one (`arch`, `cli`, `access`, `audit`, `eventbus`), so a consumer's type-checker sees
  the typed surface; `tests/guardrails/test_packages_ship_py_typed.py` prevents regression.
- [x] **Retired the vestigial `Policy.read_role` / `write_role` projection** + the
  `_legacy_role` helper (ADR 0018) — zero production readers.
- [ ] **Test over-fitting to the line-coverage gate** — some lines are reached via
  synthetic spies (`_SpySession`, `SimpleNamespace`, `object()` casts) rather than real
  behavior (adversarial review §4 Q5); prefer real fixtures as suites grow.
- [ ] **CLI render helpers tested via private import** (`_render_text` / `_render_mermaid`
  with `# type: ignore[attr-defined]`) — low priority, acceptable internal-seam testing.
- *(already tracked)* framework-only coverage at 95.5% (caps / actor binder / middleware
  exercised only by the example app); branch coverage 99% (3 documented defensive partials).

### Agent onboarding & discoverability (2026-06-25) — ADR 0019

How an agentic coder in a *consumer* repo learns correct Terp usage **without reading
the installed package**. Layered, generated-where-possible, parity-tested; channels
ranked by agent-reliability (design §9/§10, [ADR 0019](decisions/0019-agent-onboarding-and-discoverability.md)):

- [x] **`terp guide [topic]`** — a deterministic, in-terminal authoring guide (overview
  + the golden rules the gate enforces + per-topic recipes: `module` / `service` /
  `policy` / `tenancy` / `events` / `capability` / `migrations`). The agent runs it; no third-party
  reading needed.
- [x] **Consumer `AGENTS.md`** (`template/AGENTS.md`) — the always-read bootstrap
  pointer: the golden rules + "run `terp guide` / `uv run pytest`". Terse and DRY (it
  points at `terp guide` for detail).
- [x] **The gate as tutor** — `terp.arch` rules fail closed with fixable messages
  (already shipped); the highest-leverage "doc".
- [x] **`terp api-docs`** — generates `platform-api.md` + `terp_core.pyi` from the live
  `terp.core` surface (generated, not hand-written, so it cannot drift) — ADR 0039.
- [x] **`terp new module <name>`** — scaffolds the canonical five slots; the output
  passes every arch rule but the first migration (`terp migrate make`) — ADR 0039.
- [x] **Copier template** — runnable repo skeleton (`create_app` + base-profile control
  plane + example module) + CI + the generated `AGENTS.md` — ADR 0039.
- [x] **Vendored read-only `vendor/terp-core/`** + `test_vendored_core_unmodified`
  (§10) — monorepo-level visibility without editability — shipped (ADR 0034).
- [x] **"Docs can't lie" parity test (shipped, ADR 0030)** — every "enforced by `test_X`" claim in the guide
  / `AGENTS.md` maps to a real rule/test, so the instructions can't rot.
- [ ] *(optional)* a packaged **skill / MCP server** for native agent environments.

Forcing function: writing the guide surfaces ergonomic smells — the repeated CRUD
boilerplate points at `build_crud_router`, the "don't return the table model" warning
points at H3 — so each becomes a tracked roadmap item.

---

## Recently recorded

- [x] The `terp-arch` harness + `ModuleSpec.requires` boot validation are recorded
  as [ADR Decision 9](decisions/0001-terp-namespace-and-kernel-scope.md).
- [x] The governed escape-hatch opt-out (justified `# arch-allow-*` suppression +
  budget ratchet) is recorded as
  [ADR Decision 10](decisions/0001-terp-namespace-and-kernel-scope.md).
- [x] The HTTP `TenantMiddleware` + JWT `tenant` claim (auth issues it, tenancy
  binds it per request) are recorded as
  [ADR Decision 11](decisions/0001-terp-namespace-and-kernel-scope.md).
- [x] The `access` capability (RBAC permission grants + `require_permission`) and
  the `create_app` principal-seam override are recorded as
  [ADR Decision 12](decisions/0001-terp-namespace-and-kernel-scope.md).
- [x] The control-plane security registry (`SecurityConfig`), the middleware stack
  + structured logging installed by `create_app`, the extended production
  fail-fast, and the `no_adhoc_middleware` / `no_adhoc_logging_config` rules are
  recorded as
  [ADR 0005](decisions/0005-security-middleware-and-structured-logging.md).
- [x] The Tier A/B/C opinionation policy (the "quadruple" rule), the cross-cutting
  controls roadmap, the model/route authoring stance (Levels 0–2), and the Phase C
  hardening are recorded as
  [ADR 0006](decisions/0006-cross-cutting-controls-and-opinionation-policy.md).
- [x] The audit auto-emit control — the `AuditPolicy` registry, fail-closed
  auto-emit from the single `BaseService` chokepoint, the core seam +
  `terp-cap-audit` durable sink (layering), and the `mutations_emit_audit` rule —
  is recorded as
  [ADR 0007](decisions/0007-audit-auto-emit-and-the-audit-seam.md).
- [x] The event bus — the typed `EventCatalog` registry, the fail-closed `emit`
  (accepts only catalog events), the core seam + in-process `terp-cap-eventbus`
  dispatcher (layering, durable outbox deferred), the typed `ModuleSpec.emits` /
  `subscribes`, and the `events_reference_catalog` rule — is recorded as
  [ADR 0008](decisions/0008-event-bus-catalog-and-typed-emit.md).
- [x] The **authoring model & opinionation boundary** — declarative-by-default,
  constrained-imperative-by-exception, zero implicit magic in modules, every
  deviation ledgered (Target A anti-drift pursued to the extreme; Target B no-code
  rejected) — is recorded as
  [ADR 0009](decisions/0009-authoring-model-and-opinionation-boundary.md). Its first
  slice (the declarative `LifecycleEventMap`, replacing `notes`' `super()` /
  `_after_write` emit) has shipped; soft-delete (ADR 0010) and actor-stamping (ADR
  0012) followed as auto-honored model traits, leaving `build_crud_router` next.
- [x] **Soft-delete as an auto-honored model trait** — declaring `SoftDeleteMixin`
  makes `BaseService.base_query` exclude deleted rows and `delete` soft-delete
  automatically (no service code; `tasks` collapsed to a declaration + one business
  filter), policed by the two-layer `no_manual_scope_filtering` rule — is recorded as
  [ADR 0010](decisions/0010-soft-delete-trait-and-no-manual-scope-filtering.md), with
  a mixin survey (OCC/timestamps already always-on; **actor-stamping** shipped as
  ADR 0012; address = value-object only; tenancy converges later).
- [x] The **model traits vs. control-plane policy boundary** — traits on the model
  declare the *which* (soft-delete / tenant / actor-stamp per table), future
  database policies configure the app-wide *how* (retention, purge, naming,
  migrations, tenant binding), and central table allow/deny lists are rejected — is
  recorded as
  [ADR 0011](decisions/0011-model-traits-vs-control-plane-policy.md).
- [x] **Actor-stamping as an auto-honored model trait** — declaring
  `ActorStampedMixin` makes `BaseService._save` fill FK-less `created_by_id` (on
  insert) and `modified_by_id` (on every save, so a soft-delete records *who*
  deleted) from the request actor (`audit_actor_ctx`), with zero module code,
  policed by the two-layer `no_manual_actor_stamping` rule; `notes` + `tasks`
  dogfood it (tasks shows the soft-delete + actor-stamp composition) — is recorded
  as [ADR 0012](decisions/0012-actor-stamping-trait.md).
- [x] The **`users` capability + the identity/users boundary** — `identity` becomes
  a library store (drops its router/entry point) and `terp-cap-users` owns the
  admin surface at `/api/v1/users` (provision / edit / deactivate / reactivate /
  reset-password, admin-only, audited, deactivate-over-delete) over the shared
  `User` table — is recorded as
  [ADR 0013](decisions/0013-users-capability-and-identity-boundary.md). A review
  tightened it: `IdentityService` is now auth-only (no mutation side-door), and
  `BaseService._save` maps a commit-time `IntegrityError` to a typed
  `ConflictError` (uniform 409, not a leaked 500) framework-wide.
