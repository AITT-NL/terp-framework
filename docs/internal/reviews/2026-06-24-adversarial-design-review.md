# Adversarial Design Review — Terp backend framework

**Date:** 2026-06-24
**Reviewer role:** skeptical senior staff engineer / application-security architect (red team)
**Method:** every claim verified against the actual code (kernel, `terp-arch` harness, all
six built capabilities, the example app and its tests). Evidence cited inline. Open
questions were resolved by reading the relevant code (see §4).

Personas used to keep scenarios concrete: **Nora** (non-technical builder), **Aiden**
(over-eager AI agent), **Mallory** (attacker probing the API), **Sam** (maintainer at
18 months).

---

## 1. Executive verdict

The "secure / audited / correct **by construction**" thesis holds for a narrow happy path
— a single-tenant app whose authors use `BaseService` verbatim, name their session
variable `session`, and remember to pass `audit_sink=`. Outside that path it leaks
**silently**, not loudly. The two headline guarantees are the most over-claimed:

1. **"All persistence flows through one audited chokepoint"** is false in the framework's
   *own* capabilities. `TenantScopedService.create`, `AccessService.grant`, and
   `AccessService.revoke` write raw to the session and emit **no audit record**. Because
   capabilities are not arch-scanned, the `mutations_emit_audit` rule never sees them.
2. **"An AI agent cannot ship the common insecure patterns"** is false because the central
   write-bypass rule matches only four hard-coded variable names and four verbs; renaming
   the session variable or calling `session.execute(...)` evades both the rule and the
   audit trail.

The deny-by-default **authorization** guard, the `BootError`-on-missing-policy, the
production config fail-fast, and the request-scoped actor binding are genuinely solid. The
deny-by-default **audit** and **tenant isolation** are not. The framework also forbids
(`no_adhoc_middleware`) the exact operation its own tenancy capability requires
(`add_middleware(TenantMiddleware)`), so its flagship multi-tenant feature is wired only in
arch-exempt test code and is absent from the shipped composition. Net: Nora falls off a
cliff at the first custom query, multi-tenant resource, or self-service login; Aiden can
satisfy every rule while shipping an unaudited, over-exposed, cross-tenant-leaking module;
Mallory locks the whole org out through the admin surface in one request; Sam opens an
empty audit table after an incident.

---

## 2. Findings

Severity key: **Critical** (breaks a headline guarantee with a realistic trigger) ·
**High** · **Medium** · **Low**.

### Critical

#### C1 — The single audited chokepoint is bypassed inside the framework's own capabilities
- **Area:** Security / Implementation / Enforcement
- **Leak:** `TenantScopedService.create`
  (`packages/backend/capabilities/tenancy/src/terp/capabilities/tenancy/service.py`) calls
  `session.add(entity); session.commit()` directly instead of `self._save`. A tenant-scoped
  create therefore emits **no audit record**, does **no** actor-stamping, runs **no**
  `_after_write` event hook, and does **not** map `IntegrityError → 409`. Its
  `update`/`delete` are inherited (audited) — so the trail is *asymmetric*.
  `AccessService.grant` / `revoke`
  (`packages/backend/capabilities/access/src/terp/capabilities/access/service.py`) do the
  same, meaning **RBAC permission changes — the single most audit-sensitive event in the
  system — are never audited.**
- **Trigger:** Mallory gets a permission granted, or writes tenant rows; Sam opens the
  audit table after an incident and finds **zero** records for grants/revokes and for
  every tenant-scoped insert. The `mutations_emit_audit` rule is green because it scans
  only `apps/.../app/`, never the capability packages.
- **Impact:** The "unbypassable audit trail" guarantee is structurally false for the two
  capabilities built specifically for multi-tenant SaaS and RBAC.
- **Recommendation:** Route every capability write through `_save`/`_remove`. Extend the
  arch harness to scan capability packages so the framework dogfoods its own rule.

#### C2 — `mutations_emit_audit` is trivially evadable (audit bypass, no build-time catch)
- **Area:** Agent-safety / Enforcement / Security
- **Leak:** The rule fires only when the receiver name is in
  `{session, db, sess, db_session}` **and** the verb is in `{add, delete, merge, commit}`
  (`packages/backend/arch/src/terp/arch/rules/_support.py`,
  `.../rules/persistence.py`). It does **not** cover `session.execute(...)`,
  `session.exec(...)`, `session.flush()`, `bulk_save_objects`, or a session bound to any
  other name (`s`, `tx`, `conn`, `database`, `self._session`).
- **Trigger:** Aiden writes `s = ...; s.add(row); s.commit()`, or
  `session.execute(text("UPDATE notes SET title=:t"))` for a bulk rename. Both persist a
  mutation with **no audit record** and produce **zero** arch violations — even with the
  canonical name `session`. The harness self-test advertises `db.delete` as "a
  differently-named session var," quietly never testing an out-of-set name.
- **Impact:** The build-time half of the audit guarantee is hollow; it only catches code
  that already used `BaseService`.
- **Recommendation:** Make `SessionDep` hand out a write-guarded session whose mutating
  methods raise unless invoked inside `_save`/`_remove` (a runtime control that does not
  depend on AST name-matching), and broaden the rule's verb/receiver detection.

### High

#### H1 — A `Permission` in a `Policy` silently collapses to a role rank
- **Area:** Security / Agent-safety
- **Leak:** `build_guard` (`packages/backend/core/src/terp/core/app.py`) authorizes purely
  on `principal.role.rank < required.min_rank`. `AuthorizationRequirement.from_permission`
  sets `min_rank = permission.min_role.rank`
  (`packages/backend/core/src/terp/core/permissions.py`), so
  `Policy(write=Permission("invoices.approve", min_role=EDITOR))` means **"any editor may
  write."** The permission name is never consulted by the router guard; the per-subject
  grant check (`access.require_permission`) is a separate, opt-in route dependency.
- **Trigger:** Aiden declares the Permission in the Policy (it is typed, it passes
  `no_adhoc_permission_literals`), believes `invoices.approve` is enforced, and never wires
  `require_permission`. Mallory, holding any editor token, approves invoices.
- **Impact:** Fine-grained authorization is an illusion at the guard layer.
- **Recommendation:** `BootError` when a Policy declares a permission the guard cannot
  enforce, or have the guard consult the access capability for `permission`-kind
  requirements. Never silently degrade a permission to a rank.

#### H2 — Overriding `base_query` drops soft-delete *and* tenant scoping, and no rule catches it
- **Area:** Security / Agent-safety
- **Leak:** `base_query` (`packages/backend/core/src/terp/core/base_service.py`) is the only
  scoping seam, and its own docstring **invites** overriding ("Override only to add genuine
  business filters"). A subclass that writes `return select(self.model).where(...)` instead
  of `return super().base_query().where(...)` silently drops `deleted_at IS NULL` and (for
  `TenantScopedService` subclasses) the tenant predicate. The `no_manual_scope_filtering`
  rule bans *referencing* `deleted_at`/`tenant_id`, but you do not need to reference them to
  drop the filter — you just omit `super()`.
- **Trigger:** Aiden adds "show only active tasks" by overriding `base_query` without
  `super()`. Soft-deleted rows reappear; in a tenant app **every tenant's rows leak**
  through that service.
- **Impact:** IDOR / cross-tenant read through a "valid," rule-passing override.
- **Recommendation:** Make scope predicates non-overridable: compose them in a final method
  callers always run, and expose a separate `business_filters()` hook. Add a rule flagging
  a `base_query` override whose body lacks a `super().base_query()` call.

#### H3 — `response_model` rule is satisfied by the raw table model (data over-exposure)
- **Area:** Security / Enforcement
- **Leak:** `check_routes_declare_response_model`
  (`packages/backend/arch/src/terp/arch/rules/http.py`) only checks that `response_model=`
  is *present*. `response_model=Page[User]` — the table model carrying `hashed_password` —
  passes the rule and serializes the hash. Nothing forces a Read DTO distinct from the
  table model.
- **Trigger:** Aiden returns `Page[Note]` (or `User`) directly because "it already
  validates." Mallory reads password hashes / internal columns from a 200 response.
- **Impact:** OWASP "Excessive Data Exposure" with the harness green.
- **Recommendation:** Add a rule that `response_model` must not be a `table=True` model.

#### H4 — `no_cross_module_imports` only sees absolute imports; relative imports evade it
- **Area:** Enforcement / Agent-safety
- **Leak:** `iter_imports` (`packages/backend/arch/src/terp/arch/_ast.py`) yields only
  `ImportFrom` with `node.level == 0`. A relative `from ..tasks.service import TaskService`
  (level 2) is invisible, so cross-module coupling via the most common agent import style
  passes silently.
- **Trigger:** Aiden couples `notes` to `tasks` via a relative import; modules are no longer
  independent leaves; harness green.
- **Impact:** Architectural erosion the "leaf modules stay independent" claim forbids.
- **Recommendation:** Resolve relative imports to absolute before matching; add a fixture.

#### H5 — Durable audit is opt-in; production boot does not require it
- **Area:** Security / Ops / UX
- **Leak:** The default sink is `_log_sink` (logs only, no DB)
  (`packages/backend/core/src/terp/core/audit.py`). `create_app(...)` with no `audit_sink`
  yields **no queryable audit table**, and the production fail-fast checks only
  `security.production_problems()` (CORS / rate-limit) and the config guardrails (secret /
  DEBUG / SQLite / CORS) — **never** a missing durable audit sink. Worse, the
  `StructuredFormatter` drops all `extra=` fields (see M8), so the log-only fallback emits a
  content-free `"audit_event"` line.
- **Trigger:** Nora composes from the docs' minimal `create_app(specs)` and ships. No
  durable audit trail in production, and nothing warned her.
- **Impact:** The compliance story ("who did what, when") silently absent where it matters.
- **Recommendation:** In production, `BootError` if audit is enabled and the sink is still
  `_log_sink` — force an explicit `AuditPolicy.disabled(reason=...)` to opt out.

#### H6 — Admin surface has no last-admin / self-lockout protection
- **Area:** Security / Ops
- **Leak:** `users/router.py`
  (`packages/backend/capabilities/users/src/terp/capabilities/users/router.py`) lets any
  admin `deactivate_user` (including self) and `update_user` to demote any admin. The router
  is ADMIN-only, and `authenticate` refuses `is_active=False`
  (`.../identity/service.py`), so once the active-admin count hits zero the lockout is
  total.
- **Trigger:** A fat-fingered admin, or Aiden running a "deactivate inactive users" batch,
  drops active admins to zero. Recovery requires raw DB access.
- **Impact:** Trivial, unrecoverable DoS against the whole org's administration.
- **Recommendation:** Enforce a ≥1-active-admin invariant in `set_active`/`update`, and
  forbid self-deactivation; raise a typed `AppError`.

#### H7 — Bundled identity/login hard-wire the 3-tier `Roles` enum and omit the tenant claim
- **Area:** Implementation / UX / Security
- **Leak:** `IdentityService.authenticate` builds `Principal(role=Roles(user.role))`, which
  raises `ValueError` → 500 for any rank not in {10,20,30} — contradicting the
  "role-model-agnostic" claim (true only at the kernel guard). `build_login_router`
  (`.../auth/router.py`) issues `create_access_token(subject=…, role=…)` with **no tenant**,
  so `tenant_from_bearer` returns `None` and every `TenantScopedService` read is empty /
  write raises.
- **Trigger:** Nora wants five roles or any multi-tenant app. The bundled login cannot carry
  a custom rank (login 500s) or a tenant (all tenant resources empty). She must replace
  login and identity — the hard machinery the framework promised to own.
- **Impact:** The two flagship differentiators (typed custom roles, multi-tenancy) require
  abandoning the bundled identity/auth stack on day one.
- **Recommendation:** Thread `tenant` through the `Authenticator` callback and the token;
  drive identity's role through the control plane's `PermissionModel` instead of `Roles`.

#### H8 — Tenancy requires an operation the harness forbids; it is wired only in test code
- **Area:** Enforcement / Governance / Ops
- **Leak:** `TenantMiddleware` must be installed via `app.add_middleware(...)`
  (`.../tenancy/middleware.py`), but `no_adhoc_middleware` **bans** `add_middleware` in app
  code (`.../rules/http.py`). The only place it is actually wired is
  `apps/example/tests/test_tenant_middleware.py` — and `tests/` is arch-exempt
  (`_SKIP_DIRS` in `_ast.py`). The shipped `build()` never wires tenancy.
- **Trigger:** Sam tries to enable tenancy in the real app; the only documented mechanism is
  a build-time violation, forcing a budgeted escape hatch for the framework's own feature.
- **Impact:** The multi-tenant guarantee exists only in test scaffolding.
- **Recommendation:** Let `create_app` accept `middleware=[...]` (or a `tenant_resolver=`)
  so tenancy is composed through the sanctioned root and the rule stays meaningful.

#### H9 — Capability discovery has no collision, partial-failure, or version-skew handling
- **Area:** Ops / Security (supply chain) / Implementation
- **Leak:** `iter_capability_specs`
  (`packages/backend/core/src/terp/core/_internal/discovery.py`) calls
  `entry_point.load()` **unguarded**, keeps only `isinstance(loaded, ModuleSpec)`, and sorts
  by name. Consequences:
  - **Partial failure:** one installed capability that fails to import (broken dep, version
    skew, import-time error) raises and **crashes the whole boot with a raw traceback**, not
    a `BootError`. No isolation.
  - **Silent vanish:** an entry point that resolves to something other than a `ModuleSpec`
    (e.g. it points at the module, not `module`) is silently dropped — the capability
    **fails to mount with no error**.
  - **Name collision / shadowing:** two entry points whose specs share a `name` are both
    appended and both mounted at `/api/v1/<name>`; `_validate_requires` uses a name *set* so
    it never notices. A stale or malicious installed package can register an entry point
    that shadows a trusted capability's routes (dependency-confusion surface).
  - **Ordering** is alphabetical by name, not dependency order.
- **Trigger:** Sam upgrades one capability; an unrelated installed `terp-cap-*` is now
  incompatible and the entire app refuses to boot with a stack trace. Or an attacker who can
  influence the dependency set ships a package whose entry point duplicates `users`.
- **Impact:** Fragile boot, silent mis-mounts, and a router-shadowing supply-chain vector.
- **Recommendation:** Wrap each `load()` in try/except → `BootError` naming the offending
  entry point; reject duplicate names; warn (or `BootError`) when an entry point does not
  resolve to a `ModuleSpec`.

### Medium

- **M1 — Hard delete leaks a raw 500 on constraint violation.** `_remove`
  (`.../core/base_service.py`) commits with no `IntegrityError → ConflictError` mapping
  (only `_save` has it). Deleting a row referenced by an FK returns a bare 500, breaking the
  uniform-envelope guarantee. *Fix:* wrap `_remove`'s commit identically.
- **M2 — Input length cap is name/shape-scoped.** **[Resolved — ADR 0025.]**
  `check_input_str_fields_have_max_length` scans only classes ending `Create`/`Update` or
  extending `BaseTable`, and `_is_str_annotation` matches only `str`/`str | None`. A body
  model named `LoginRequest`/`SearchFilter`/`NotePayload`, or fields typed
  `list[str]`/`dict[str,str]`, escape the cap → request-size DoS. *Fix:* key off "is a
  request-body model" not the name suffix; recurse into containers.
- **M3 — `-> None` route can still return ORM data.** **[Resolved — ADR 0025.]** The response-model rule exempts
  routes annotated `-> None`, but Python does not enforce return annotations; `def x() ->
  None: return note` serializes the ORM object. *Fix:* exempt only 204/empty-body routes.
- **M4 — JWT has no revocation; authz is frozen in the token for its TTL.**
  `decode_access_token` (`.../auth/tokens.py`) reconstructs `Role(name, rank)` straight from
  claims; there is no per-request re-fetch. A demoted/deactivated/re-tenanted user keeps the
  old rank and tenant for up to 30 min. *Fix:* short TTL + refresh rotation + a deny-list
  seam; re-check `is_active` on sensitive routes.
- **M5 — Mandatory exact `COUNT(*)` per list.** `_paginate` runs `SELECT count(*) FROM
  (subquery)` on every page; on large tables this dominates cost and there is no
  cursor/approximate option. *Fix:* offer keyset pagination / opt-out of total.
- **M6 — Over-posting depends entirely on schema narrowness, unchecked.** **[Resolved — ADR 0025.]** `create` does
  `self.model(**data.model_dump())` and `update` does `setattr` per dumped field. A
  too-wide Create/Update schema mass-assigns privileged columns; no rule audits schema field
  safety. *Fix:* a rule that input schemas may not declare framework-managed or model-private
  columns.
- **M7 — CSRF is a consumer-wide bet, undocumented as a constraint.** The design drops CSRF
  ("Bearer, not cookies"), but nothing stops a consumer storing the JWT in a cookie for a
  browser SPA, at which point there is no CSRF defense. *Fix:* document "tokens must never be
  sent as cookies" as a supported-configuration constraint; consider an origin-check seam.
- **M8 — `StructuredFormatter` drops every `extra=` field.** **[Resolved — ADR 0025.]** `format()`
  (`.../core/logging.py`) emits only `level/logger/request_id/message` (+`exc_info`). So the
  log-only audit sink's `extra={audit_action, audit_target, audit_actor, audit_payload}`
  never reaches the JSON line, and any debugging `extra` is invisible. This hollows the H5
  log fallback and weakens observability. *Fix:* serialize redacted, non-standard record
  attributes into the JSON payload.
- **M9 — Redaction is prefix-gated for free text.** `RedactingFilter` (`.../core/logging.py`)
  catches `Authorization:`/`Bearer ` substrings and sensitive *keys* in dicts/extras, but a
  free-text secret without that prefix (`log.info("token=%s", t)` → `"token=…"`) passes
  through. *Fix:* add high-value value patterns (JWT-shaped, `key=value` for sensitive
  keys), and prefer structured logging over interpolated secrets.

### Low

- **L1 — `tests/` and `migrations/` are global rule blind spots** (`_SKIP_DIRS` in
  `_ast.py`). Real logic parked in a `tests/` helper or a future Alembic migration bypasses
  every rule.
- **L2 — `_service_model` only resolves `model = <Name>`** (`.../rules/_support.py`); a model
  bound by alias or indirection makes `tenant_scoped_models_use_scoped_service` silently
  pass.
- **L3 — Rate limiting is per-instance** (known) and there is no login-specific
  throttle/lockout, so horizontal scaling dilutes it and credential-stuffing is open.
- **L4 — `Page.of` requires manual `Read.model_validate(row)` in every router**; forgetting
  it yields ORM-in/ORM-out (ties to H3).
- **L5 — Two disconnected CORS configs.** `settings.BACKEND_CORS_ORIGINS` (checked by the
  config guardrail) is separate from `SecurityConfig.cors` (used by the middleware); setting
  one does not affect the other — a confusing footgun.

### Genuinely solid (kept short on purpose)
- Deny-by-default **authorization** guard + `BootError` on missing `Policy` is real and
  fail-closed.
- The audit-actor binder correctly uses an **async** yield-dependency to avoid cross-context
  `ContextVar` leakage — a subtle correctness win.
- The `_save` `IntegrityError → 409` mapping and centralized redaction-of-keys are well done.
- Production config fail-fast (weak secret / DEBUG / SQLite / wildcard CORS) is enforced at
  settings construction.
- The escape-hatch budget ratchet and the harness self-completeness meta-test are good
  governance *mechanics*; their weakness is coverage, not design.

---

## 3. The 3–5 highest-leverage fixes

1. **Make the chokepoint structural, not name-based (fixes C1, C2, M6, H3).** Replace the
   AST allowlist with a write-guarded `Session` handed out by `SessionDep`: its
   `add/delete/merge/commit/execute/flush` raise unless invoked from within `_save`/`_remove`.
   A runtime, fail-closed control that does not care what the variable is named or which
   capability wrote it — it would have caught `TenantScopedService.create` and
   `AccessService.grant` immediately.
2. **Scan capabilities with the harness (fixes C1, C2; closes the "caps aren't scanned"
   gap).** Run `check_app` over each `terp.capabilities.*` package in CI. The framework must
   dogfood the rules it sells.
3. **Close the authorization-semantics gap (fixes H1).** Enforce `Permission` requirements at
   the guard, or `BootError` when a Policy declares a permission the guard cannot enforce.
4. **Make scope predicates non-overridable and require durable audit in prod (fixes H2, H5).**
   Split `base_query` into a final scoped core + a `business_filters()` hook; `BootError`
   when audit is enabled but the sink is still log-only.
5. **First-class multi-tenant + custom-role path (fixes H7, H8, H9).** Thread `tenant`
   through the authenticator and token, install `TenantMiddleware` via `create_app(...)`,
   drive identity's role through `PermissionModel`, and harden capability discovery.

---

## 4. Open questions — resolved

1. **Does entry-point discovery handle collisions / partial failure / version skew?**
   **No.** `iter_capability_specs` (`.../core/_internal/discovery.py`) loads every
   `terp.capabilities` entry point **unguarded**: one failing import crashes the whole boot
   with a raw traceback; a non-`ModuleSpec` result is silently dropped (the capability
   vanishes); duplicate names both mount at the same prefix (router shadowing /
   dependency-confusion); ordering is alphabetical, not dependency-based. Captured as **H9**.

2. **Are events lost on crash between commit and dispatch?** `dispatch_in_process`
   (`.../capabilities/eventbus/dispatcher.py`) runs handlers **synchronously, before the
   commit** (via `_after_write`), so in-process handlers ride the same transaction and a
   raising handler rolls the write back — good. But delivery is **in-process, at-most-once,
   to handlers registered at import time**: (a) a handler doing external I/O (HTTP, email)
   creates a dual-write hazard — the side effect fires even if the later commit fails; (b)
   any multi-instance deployment loses cross-instance events entirely, with no signal. The
   durable outbox is deferred (known); the concrete residual risk is the side-effecting
   handler and the multi-instance gap. (Relates to M4-class staleness rather than a new
   high finding.)

3. **What exactly does `production_problems()` enforce for secret / CORS?**
   `SecurityConfig.production_problems` (`.../core/security.py`) checks **only** three
   things: CORS unset, CORS wildcard, rate-limit disabled. The **SECRET_KEY** strength check
   lives elsewhere — `Settings._enforce_production_guardrails`
   (`.../core/config.py`) refuses to construct in production on weak secret (`< 32` chars or a
   placeholder), `DEBUG`, SQLite, or `*` in `BACKEND_CORS_ORIGINS`. So the secret *is* gated
   (at settings construction). Two gaps surfaced: a missing durable audit sink is gated by
   **neither** path (**H5**), and `BACKEND_CORS_ORIGINS` (config) is disconnected from
   `SecurityConfig.cors` (middleware) (**L5**).

4. **Can the redacting filter be defeated by nesting / non-string keys?** Not by nesting per
   se — `_scrub` recurses into dicts/lists/tuples and coerces keys via `str(key)`. But
   redaction is **incomplete in two ways**: free-text secrets without an
   `Authorization`/`Bearer` prefix are not matched (**M9**), and the `StructuredFormatter`
   **drops all `extra=` fields from the JSON output entirely** (**M8**) — so redaction of
   extras is moot for the emitted line and the log-only audit fallback is content-free.

5. **Does the 100% coverage gate push toward over-fitting?** **Yes, partly.** The gate is
   **100% line** (not branch) coverage over `terp.*`. Several lines are covered by synthetic
   spies — `_SpySession`, `SimpleNamespace` entities in the event-hook tests — that do not
   reflect real DB behavior; the actor-stamping check was even shaped (`isinstance(entity,
   …)`) to satisfy those spies. Key end-to-end guarantees are proven only on synthetic
   fixtures or not at all: tenant isolation is exercised via a synthetic `_Widget` at the
   service layer and a test-only `add_middleware`; there is **no** test that a tenant create
   is audited (because it is not — C1); the example `app/` has no tenant-scoped model, no
   permission-gated route, and no access grants, so `tenant_scoped_models_use_scoped_service`
   and the permission path are never exercised against a real consumer. Line coverage
   measures lines executed, not invariants held.

---

## 5. Status of fixes (this review is being acted on)

Recorded in [ADR 0014](../decisions/0014-adversarial-review-hardening.md) and
`docs/STATUS.md`. Gate after this batch: **282 tests, 100% framework line coverage.**

**Shipped (each with a runtime control + a build-time test):**
- **C1** — `TenantScopedService.create` and `AccessService.grant`/`revoke` now route
  through the audited `_save`/`_remove` chokepoint; tenant creates and grant/revoke
  are audited.
- **Capability arch-scan** — the `terp.arch` harness now runs over every capability
  package (the three legitimate framework primitives carry justified, budgeted
  `# arch-allow-*` markers); a drift guard fails if a new capability is unscanned.
- **C2 (build-time)** — `mutations_emit_audit` now catches bulk/flush verbs,
  inline and precomputed DML via `execute`/`exec`, avoids `text('SELECT ...')`
  false positives, and treats `Session`/`SessionDep` receivers as function-scoped
  symbols (renaming no longer evades it, unrelated same-named variables are clean).
- **H4** — `no_cross_module_imports` resolves relative imports, including
  package-alias imports such as `from .. import sibling`.
- **M1** — `_remove` maps a constraint violation to a uniform 409.
- **H6** — last-admin / self-lockout protection in the users surface
  (`LastAdminError` / `SelfAdminActionError` → 409) with row locks where supported.
- **H5** — production boot requires a marked `DurableAuditSink`; an unmarked
  callable/no-op lambda no longer satisfies the audit trail requirement.
- **H9** — capability discovery fails closed on load failure, non-`ModuleSpec`,
  duplicate capability names, and duplicate names across explicit + discovered specs.
- **Runtime write-guarded session (ADR 0015)** — `SessionDep` hands out a
  `WriteGuardedSession` whose `add` / `delete` / `merge` / `commit` / `bulk_*` /
  DML `execute` / `exec` raise `UnauditedWriteError` outside the `BaseService`
  `_save` / `_remove` write scope, so a write that skips the audited chokepoint
  fails closed at runtime regardless of the session variable's name — the
  structural primary control for C1 / C2, with `mutations_emit_audit` kept as the
  build-time second layer.
- **Permission-in-`Policy` enforcement (ADR 0016, H1)** — a `Policy` permission
  requirement is now enforced as a real per-subject grant (the `min_role` rank floor
  **and** the granted permission, via the injected `permission_enforcer` seam), and
  `create_app` fails closed at boot when a permission policy has no enforcer — never a
  silent collapse to a role rank.
- **Non-overridable scope predicate (ADR 0017, H2)** — `base_query` is a central,
  non-overridable composition (soft-delete + a capability scope-predicate registry +
  a `business_filters()` hook); a service adds read filters via `business_filters`
  (which can only narrow), and the `base_query_not_overridden` rule forbids overriding
  `base_query`, so a `super()`-less override can no longer silently drop soft-delete or
  tenant scope. Tenancy registers its predicate (no more `super().base_query()`).

**Sequenced next (their own decisions — see the STATUS deferred backlog):** the
`response_model`-not-a-table rule (H3), and first-class tenancy/role wiring (H7,
H8). The Medium/Low items (M2–M9, L1–L5) are triaged in the findings above.
