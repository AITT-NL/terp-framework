# 0023 - `build_crud_router`: the CRUD-router factory (Tier-C sugar)

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile)
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the opinionation tiers — this is the Tier-C "Level-1" sugar ADR 0006 said to
  ADOPT), [ADR 0020](0020-response-model-not-table-model.md) (`response_model` must
  be a DTO — satisfied by construction here), [ADR 0019](0019-agent-onboarding-and-discoverability.md)
  (writing `terp guide` was the forcing function that flagged the repeated CRUD
  boilerplate), [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (the `BaseService`
  shape this wraps).

---

## Context

The hand-written module routers (`notes`, `tasks`, `projects`) repeat the same
five-route CRUD shape almost verbatim: a paginated list returning `Page[Read]`, a
201 create, a get, an optimistic-concurrency update, and a 204 delete — each
wrapping a `BaseService` and `.model_validate`-ing the row into the `*Read` DTO.
ADR 0006 had already classified a CRUD-router factory as Tier-C "Level-1" sugar to
ADOPT (code stays the source of truth; native FastAPI is always allowed), and the
`terp guide` write-up (ADR 0019) flagged the repetition as the concrete candidate.

## Decision

Add `terp.core.build_crud_router(service, *, read_schema, create_schema,
update_schema, tags=None) -> APIRouter`: a factory that generates the five canonical
secure routes over a `BaseService` + its DTOs and returns a **native** `APIRouter`.
Every generated route is exactly what the hand-written module writes — the list
paginates, writes route through the audited `BaseService` chokepoint, and every
response is the `*Read` DTO (never the table model), so the runtime response-model
guard (ADR 0020) is satisfied by construction.

The endpoints are built as closures whose `__annotations__` are bound to the
concrete per-call types (the DTO classes, the `uuid` id, `SessionDep` /
`PaginationDep`), so FastAPI derives the request/response shape at runtime exactly
as for a hand-written route. The factory is a convenience, not a new layer: a module
that needs anything bespoke (a query filter, an in-transaction side effect, a
non-CRUD action) still writes its routes by hand — `notes` (lifecycle events) and
`tasks` (a status filter) keep doing so.

The example's tenant-scoped `projects` module — pure CRUD — adopts it: its router
collapses from five hand-written routes to one `build_crud_router(...)` call, and
tenant isolation is unchanged (it lives in the scoped service, not the routes).

## Consequences

- A pure-CRUD module is one factory call; the boilerplate the review and the guide
  flagged is gone where it adds no value.
- Security is preserved by construction: DTO responses (ADR 0020), mandatory
  pagination, the audited write chokepoint, and the deny-by-default guard
  `create_app` still mounts the router behind.
- It lives in `terp.core` — it composes only kernel primitives (`BaseService`,
  `Page`, `SessionDep`) — so it needs no capability install and is available to
  every app.

## Alternatives considered

- **A declarative model→router DSL (Level-2).** Rejected per ADR 0006: code stays the
  source of truth; a factory returning a native `APIRouter` keeps the output
  inspectable and overridable, where a DSL would hide it.
- **Put it in a capability.** Rejected: it has no external dependency and composes
  only kernel types; a capability install would be friction for a universal
  convenience.
- **Generate the routes via codegen (a scaffold).** Rejected for the runtime case: a
  live factory needs no file to maintain and cannot drift from the service. CLI
  scaffolding (`terp new module`) remains a separate, complementary Tier-C track.

## Update (2026-06-25, review hardening)

`build_crud_router(read_schema=<table model>)` would expose the table model through
the generated routes. It is rejected at boot by the ADR-0020 runtime guard, and the
build-time `response_model_not_table_model` rule now also inspects
`build_crud_router(..., read_schema=...)` calls — so the misuse fails at the harness
with a fixable file/line message, restoring the two-layer pair for the factory.
