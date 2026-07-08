# 0060 - `projects` is example code; the base profile closes without a projects capability

- **Status:** Accepted
- **Date:** 2026-07-03
- **Context phase:** Phase 2 (capability repackaging) closure
- **Relates:** [ADR 0023](0023-build-crud-router.md) (the example `projects` module is the
  `build_crud_router` dogfood), [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (the
  product-vocabulary-free kernel scope), [ADR 0052](0052-retire-vestigial-backend-nav.md)
  (precedent for amending the design when code has answered a deferred question).

---

## Context

The design's §13 Phase 0 triage listed **projects** among the capability candidates, and
the Phase 2 gate defined the base profile as *core + auth + access + identity + users +
projects*. Every other base-profile entry shipped as a packaged capability; `projects`
never did. What exists instead is `apps/example/app/modules/projects` — a 124-line
tenant-scoped **module** whose entire surface is one `name` column served by
`build_crud_router` over a `TenantScopedService`. It is the example app's Tier-C CRUD
demonstration (ADR 0023) and the tenancy dogfood, not a reusable platform feature.

Packaging it would invert the platform's own classification rule. Capabilities exist for
**cross-cutting concerns** (auth, access, audit, files, webhooks — things every app needs
and no app should hand-roll). A "project" is a **business noun**: what a project *is*
(fields, workflow, ownership, relations) is exactly the per-client vocabulary the design
says belongs in client modules — the only editable surface. A shipped `terp-cap-projects`
would either be an empty name-holder (no platform value, but a frozen table shape every
consumer inherits) or a growing opinion about clients' domain models (vocabulary drift
into the platform, against ADR 0001's spirit one layer up).

The "10-minute module" story (design Appendix A) also *depends* on projects-like nouns
being modules: `terp new module billing` is credible precisely because the example app
shows a real business noun built the same way.

## Decision

**Remove `projects` from the base profile and from the capability triage list.** The base
profile (design §13 Phase 2) is **core + auth + access + identity + users**. The
`projects` code stays where it is — the example app's `build_crud_router` + tenancy
dogfood module — and is the canonical demonstration that business nouns are client
modules, not capabilities.

With every base-profile capability shipped (auth, access, identity, users), **the Phase 2
gate closes**.

## Consequences

- `AGENTIC_PLATFORM_DESIGN.md` is amended: the §13 triage list and Phase 2 base profile no
  longer name `projects`; the package/dependency illustrations drop `terp-cap-projects`.
- `docs/internal/STATUS.md` marks Phase 2 ✅ and retires the `terp-cap-projects` checkbox
  in favour of this decision.
- No code changes: nothing imported, published, or scaffolded a `terp-cap-projects`
  distribution.
- A future genuinely cross-cutting "project/workspace grouping" need would be a **new**
  decision with its own justification — this ADR only settles that the example module is
  not silently owed a packaged twin.

## Alternatives considered

- **Ship `terp-cap-projects` as packaged CRUD.** Rejected: it has no cross-cutting
  content; it would freeze a domain shape the design deliberately leaves to clients, and
  the capability wiring cost (workspace, arch lists, migrations conformance, contract
  regeneration) buys nothing a module doesn't already prove.
- **Keep the checkbox open indefinitely.** Rejected: an unclosable gate is drift; the
  status tracker must reflect a decision, not a stall.
