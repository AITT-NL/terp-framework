# 0028 - Adversarial-review third batch (F1–F3): closing the read-path and authorization-tier leaks

- **Status:** Accepted
- **Date:** 2026-06-26
- **Context phase:** Phase 2 (base profile), continuing the adversarial-review follow-ups
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (two-layer discipline), [ADR 0015](0015-runtime-write-guarded-session.md)
  (the runtime write guard — F1/F2 extend it),
  [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) and
  [ADR 0026](0026-adversarial-review-second-batch.md) (the F1 row-scope backstop this
  completes), [ADR 0027](0027-packaged-migrations-per-package-histories.md) (the
  migration control F3 completes), [ADR 0019](0019-agent-onboarding-and-discoverability.md)
  (the `terp guide` surface F1 corrects). Findings: a third adversarial review
  (2026-06-26) that audited the second batch's fixes and found three residual leaks
  one step past where those fixes stopped, plus two findings deliberately **not**
  code-changed (recorded below).

---

## Context

ADR 0026 (F1) re-applied row scope at the request session for a bespoke
`session.exec(select(self.model))` read. A fix audit found the backstop, and two
other newly-frontier controls, over-claimed one step further:

- **F1 (High) — the row-scope backstop missed `session.get()` / `scalars()`.** The
  ADR-0026 backstop re-scoped only `WriteGuardedSession.exec(select(model))`. A
  primary-key load — `session.get(ScopedModel, id)`, the single most idiomatic
  SQLModel/SQLAlchemy fetch — bypasses `base_query` and the row predicates entirely,
  and has **no `select(...)` node** for the `reads_use_base_query` rule to see, so it
  was caught by **neither** layer: a cross-tenant IDOR and a soft-delete bypass through
  a custom read. `session.scalars()` / `scalar()` route through `execute` (not `exec`),
  so they were not re-scoped at runtime either. Worse, the `terp guide` service recipe
  told agents a raw read is "re-scoped anyway" — vouching for the leak.
- **F2 (Medium) — authorization tier is chosen by HTTP method, so a mutating safe
  method runs at the read tier.** The deny-by-default guard authorizes a request by
  HTTP method (`request.method in {POST,PUT,PATCH,DELETE}` ? write : read). A handler
  bound to a safe method (`GET`/`HEAD`/`OPTIONS`) that mutates therefore performs a
  write a *read-tier* caller cleared — a vertical privilege escalation (a viewer
  triggering an editor/admin write via a `GET`) that no rule and no runtime control
  caught.
- **F3 (Medium) — no layer ensures a new table has a migration.** The boot guard
  `assert_migrations_current` checks only *declared* histories (capability entry
  points + app modules that ship a `migrations/` directory). An app module that
  declares a `table=True` model but ships no migration is invisible to it, so the table
  would simply be missing in a production deploy (which builds its schema from
  migrations, not `create_all`) with a green gate and a passing boot — the
  `tables_have_migrations` build rule was deferred at ADR 0027.

## Decision

Each leak is closed with the ADR-0006 two layers — a fail-closed runtime control
**and** a build-time rule (F1/F2) — or the deferred build rule plus a doc correction
(F3).

1. **F1 — re-scope every user-facing read shape (runtime), extend the rule (build).**
   - `WriteGuardedSession.get(entity, ident)` now, when row scope narrows the model
     (`apply_row_scope(model, select(model))` changes the query), re-issues the
     primary-key load as a scoped query, so a hidden / out-of-tenant row is filtered
     out; an unscoped model keeps the parent's identity-map fast path. When `get()` is
     called with options (`with_for_update` / loader `options` / `populate_existing`),
     the guard confirms scope visibility with a primary-key-only probe (which loads no
     entity, so a `with_for_update` still locks) and then delegates to the parent
     `get()`, so the options are honored exactly rather than silently dropped. `scalars()` /
     `scalar()` now re-scope a single-entity `select(model)` like `exec` (and require
     the write scope for a DML statement). `execute` is still **not** re-scoped (the
     ORM's internal load path), as in ADR 0026.
   - `reads_use_base_query` now also flags `session.get(<ScopedModel>, …)` — matched
     directly (its first positional argument is the scoped model class), since it has
     no `select(...)` node; `self.get(session, id)` / `_service.get(session, id)` pass
     a session first, not a model, so they are not flagged.
   - The `_scoped_read` docstring no longer claims it closes "every shape", and the
     `terp guide` service recipe now reads "never `select(Model)` and never
     `session.get(Model, id)` … read a single row with `self.get(session, id)`",
     deleting the "re-scopes it anyway" sentence that green-lit the leak.

2. **F2 — `safe_methods_are_read_only` (build) + a read-only request scope (runtime).**
   - `WriteGuardedSession` gains a `read_only_request` `ContextVar`; `create_app`
     mounts `build_read_only_request_binder` on every module router (beside the
     audit-actor binder, async so the flag propagates into the threadpooled sync
     route), which marks a safe-method request read-only. A `BaseService` write during
     such a request fails closed with `ReadOnlyRequestError` (a generic 500) even
     inside the chokepoint's `allow_session_writes` scope.
   - The `safe_methods_are_read_only` rule flags a handler **reachable via** a safe
     method (a `@x.get` decorator, or an `api_route` / `add_api_route` whose methods
     *include* a safe one — a mixed `["GET", "POST"]` route counts, since the `GET`
     invocation runs at the read tier; the imperative `add_api_route` endpoint is
     resolved to its `def`) that calls a mutating `BaseService` method (`_save` /
     `_remove`, or `create` / `update` /
     `delete` on a `self` / `*service*` receiver). Put the write behind a
     `POST`/`PUT`/`PATCH`/`DELETE` route so it is authorized at the write tier.

3. **F3 — `tables_have_migrations` (build) + boot-guard doc correction.** The rule
   flags an `app/modules/<name>` that declares a `table=True` model but ships no
   `migrations/versions/` revision (`terp migrate make <name>` fixes it). It is scoped
   to app modules — a capability ships its history via a `terp.migrations` entry point
   (declared in packaging, invisible to a source scan), and a non-module table model is
   covered by the existing `make`-time homeless-table check. The
   `assert_migrations_current` docstring now states it guards only *declared* histories
   and points at this rule as its build-time complement.

4. **F4 / F5 — assessed, deliberately not code-changed.**
   - **F4 (UX/Philosophy).** The "a non-technical person declares policy and gets a
     safe API" pitch over-claims relative to authoring being typed Python (generics,
     OCC `version`, DI). This is **already the repository's own honest position**:
     [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) rejected "no code in
     modules", and the README / ADR 0009 frame the audience as "non-technical owners
     *working through coding agents*", not hand-coding. The over-claim lives only in an
     external pitch, so there is nothing in-repo to change; the Phase-5 scaffolding /
     cookbook is the tracked on-ramp.
   - **F5 (Governance).** The escape-hatch justification is unchecked free text, so a
     determined agent can suppress a rule with a plausible reason plus a budget bump.
     This is the accepted ADR-0006 design: the budget ratchet makes every new opt-out a
     reviewable diff, and the framework's own legitimate suppressions (the audit sink's
     `mutations_emit_audit`, the append-only `AuditEvent`'s `table_models_use_base_table`)
     mean Tier-A rules **cannot** be made blanket-non-suppressible without breaking the
     platform. The residual is inherent to any escape hatch and is left as a social /
     review control, not a code change.

## Consequences

- `session.get` / `scalars` / `scalar` of a soft-delete / tenant model no longer leak
  a hidden or cross-tenant row, at runtime and (for `get`) at build time; the agent
  guide no longer vouches for the unsafe shape.
- A mutating safe-method handler fails closed at runtime and red at build time, so the
  HTTP-method-derived authorization tier can no longer be under-cleared.
- A new app module with a table model but no migration fails the build instead of
  deploying table-less.
- Two new `terp.arch` rules (`safe_methods_are_read_only`, `tables_have_migrations`),
  each in `_ALL_RULES`, exported, and paired with a `test_<rule>` (the self-completeness
  meta-test enforces the pairing); `reads_use_base_query` extended. The example app and
  every capability stay clean — all escape-hatch budgets remain `{}` / unchanged.
- 421 tests, 100% framework line coverage.
- **Residual (documented):** the runtime read-only guard is a `WriteGuardedSession`
  control, so a write through a bare `Session` in a safe-method handler is caught only
  by the build rule — the same session-method-guard boundary noted in ADR 0015/0026.
  The migration homeless check stays at `make` time / the build rule rather than the
  runtime boot guard, to avoid coupling the boot guard to global mapper-registry state.
