# 0026 - Adversarial-review second batch (F1–F5): closing the post-fix leaks

- **Status:** Accepted
- **Date:** 2026-06-26
- **Context phase:** Phase 2 (base profile), continuing the adversarial-review follow-ups
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (two-layer discipline + the Tier-A "quadruple"), [ADR 0014](0014-adversarial-review-hardening.md)
  (the first review batch), [ADR 0015](0015-runtime-write-guarded-session.md)
  (the runtime write guard — F3/F5 extend it), [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md)
  (the non-overridable `base_query` — F1 extends it),
  [ADR 0021](0021-create-app-middleware-seam.md) (the middleware seam — F4 fixes its
  doc drift). Findings: a second adversarial review (2026-06-26) that *audited the
  first batch's fixes for completeness* and found five residual leaks slipping past
  the newest controls.

---

## Context

The first adversarial-review batch (ADR 0014 and the structural follow-ups
0015–0022) closed the catalogued leaks **where they were catalogued**. A second
review audited those fixes and found that two headline guarantees were over-claimed
*one step past* where the fixes stopped, plus three smaller residuals — each
re-triggering a supposedly-closed class through a door the fix left open:

- **F1 (High).** ADR 0017 made `base_query` non-overridable, but the
  `base_query_not_overridden` rule only fires on a method *named* `base_query`, and
  `no_manual_scope_filtering` only fires on *referencing* a managed column. A bespoke
  read method that issues `select(self.model)` directly (a search / "my items" /
  ownership filter — the most common real feature, in the universal SQLModel idiom)
  composed **none** of the registered scope predicates, silently dropping soft-delete
  and the tenant filter — a cross-tenant read leak with a green gate.
- **F2 (Medium).** "Mandatory capped `Page[T]` pagination" (ADR 0006, Tier A) was a
  registry + default only: no rule and no runtime control forced a list route to
  paginate, so `response_model=list[X]` returning all rows shipped clean — the
  quadruple was hollow for pagination.
- **F3 (Medium).** The runtime write guard (ADR 0015) intercepts the request
  `Session`'s methods, but the bound `Engine`/`Connection` it exposes is a second
  surface: `session.get_bind().connect().execute(<DML>)` persisted unaudited with no
  `UnauditedWriteError`.
- **F5 (Low–Medium).** `BaseService._save`/`_remove` ran the subclass `_after_write`
  hook *inside* `allow_session_writes()`, so a raw session write there was runtime-
  permitted (only the evadable build rule guarded it) — re-opening the exact
  rename/raw-write class ADR 0015 closed everywhere else.
- **F4 (Medium, doc-drift).** ADR 0021 replaced `add_middleware(TenantMiddleware)`
  with `create_app(middleware=[…])`, but the tenancy capability's own docstring (and
  `terp guide tenancy`) still showed the gate-forbidden `add_middleware` form — the
  only concrete wiring example a consumer/agent would copy was the one
  `no_adhoc_middleware` rejects.

## Decision

Each leak is closed with the ADR-0006 two layers — a fail-closed runtime control
**and** a build-time rule — except F4 (a documentation control surface).

1. **F1 — row scope is re-applied at the request session (runtime), with a build
   rule as the early warning.**
   - `terp.core.scoping.apply_row_scope(model, query)` is now the single definition
     of "row scope" (soft-delete + every registered predicate), composed by
     `BaseService.base_query` **and** re-applied by `WriteGuardedSession.exec` to any
     **single-entity** `select(model)` — so a custom `session.exec(select(self.model))`
     is scoped even though it never called `base_query`. It is idempotent (double
     application is a no-op in effect) and a no-op for a model with no scope trait.
     Only `exec` (the SQLModel user-facing read) is re-scoped — **not** `execute`,
     which the ORM itself uses internally for `refresh` / lazy-loads (scoping those
     would, e.g., make a just-soft-deleted row unrefreshable); the build rule covers
     the rarer `execute` path. Only the request session re-scopes, so a bare
     `Session` (a test, a deliberate privileged read) is unaffected.
   - The `terp.arch` `reads_use_base_query` rule flags raw reads of a
     `SoftDeleteMixin` / `TenantScopedMixin` model (the build-time early warning),
     including `select(self.model)`, `select(type(self).model)`, qualified/attribute
     forms, every entity in a multi-entity `select(...)`, and `select_from(Model)`.

2. **F2 — `list_routes_paginate`.** A route whose `response_model` is a bare
  `list[...]` / `list` / `Sequence[...]` (not `Page[...]`) is flagged, including
  `@router.api_route(...)` and imperative `add_api_route(...)`; the runtime cap
  already exists in `PaginationDep` / `Page`, so this rule makes its use mandatory
  rather than conventional, completing the Tier-A quadruple for pagination.

3. **F3 — `connection()` guard + `no_raw_connection_access`.**
  `WriteGuardedSession.connection()` now requires the write scope (the ORM uses the
  private bind resolver internally, so reads are unaffected). A fresh connection from
  `session.get_bind().connect()` is a separate transaction the method guard cannot
  reach, so the `no_raw_connection_access` rule forbids `get_bind` / `connection` — a
  `get_bind().connect()` escape is caught at the `get_bind` call, and raw engine
  *construction* (`create_engine` / `sessionmaker`) is separately banned by
  `no_raw_session_construction`, so an unrelated `.connect()` on a domain object (a
  websocket / cache / search client) is deliberately not flagged.
  ADR 0015's completeness claim is corrected to name this boundary.

4. **F5 — `forbid_session_writes()`.** `BaseService` now wraps the `_after_write`
   hook in `forbid_session_writes()` (a `ContextVar` flip), so a raw `session.add` /
   `commit` there fails closed; the hook may still `emit` an event (which never
   touches the session) or call `self._save` / `self._remove` (which re-open the scope
   for their own audited write).

5. **F4 — docs + tenant fail-closed robustness.** The `TenantMiddleware` docstring,
  `terp guide tenancy`, and the older ADR 0001 example now show the
  `create_app(middleware=[Middleware(TenantMiddleware, resolve_tenant=…)])` seam
  (and the `build_login_module(tenant_resolver=…)` token side), never
  `add_middleware`. The tenant predicate now explicitly returns `false()` when no
  tenant is bound, instead of relying on `tenant_id IS NULL` plus a non-null column.
  Direct nested reset tests cover both `tenant_context` and `bind_audit_actor`.

## Consequences

- A custom read method can no longer silently drop soft-delete / tenant scope: the
  request session re-applies it structurally, and the build rule flags the raw shape.
  The `terp guide` service recipe now states "every read builds on `base_query()`".
- Pagination is enforced, not conventional; the engine-escape is closed at build time
  and the session-bound `connection()` at runtime; the `_after_write` hook is no longer
  an open write scope; and the multi-tenant wiring is discoverable through the
  sanctioned seam.
- Three new `terp.arch` rules (`reads_use_base_query`, `list_routes_paginate`,
  `no_raw_connection_access`), each in `_ALL_RULES`, exported, and paired with a
  `test_<rule>` (the self-completeness meta-test enforces the pairing). The example
  app and every capability stay clean — all escape-hatch budgets remain `{}` / unchanged.
- 359 tests, 100% framework line coverage.
- **Residual (documented):** the `get_bind().connect()` engine escape has no runtime
  closure (only the build rule), like the `row.title = x` attribute-mutation residual
  in ADR 0015 — both need change-tracking / engine-level interception, a deeper control
  than session-method guarding, tracked for a later decision.
