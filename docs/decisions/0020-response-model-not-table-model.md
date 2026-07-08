# 0020 - `response_model` must be a read DTO, never a table model

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0014](0014-adversarial-review-hardening.md) (the adversarial
  review this closes — finding **H3**), [ADR 0003](0003-conformance-and-coverage-gate.md)
  (the conformance + 100%-coverage gate the new rule joins),
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the two-layer
  / quadruple control model every control ships as). Finding **H3** in
  [docs/internal/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

The HTTP boundary already requires a `response_model` on every content route
(the `routes_declare_response_model` rule) — but that rule only checks
**presence**. A route can declare `response_model=User` (or `Page[User]`), and
because a SQLModel `table=True` model is *also* a valid Pydantic model, FastAPI
serializes it happily — **including `hashed_password`** and every other internal
column. "Declared a response model" is not "declared a *safe* response model":
the single most sensitive leak — a password hash — sails straight through the
existing rule. (H3.)

Terp deliberately keeps the table model and the read DTO as different types
(`User` vs `UserRead`, `BaseTable` vs `BaseSchema`) precisely so the wire shape
is an explicit allow-list of fields. Nothing enforced that they stay distinct on
the way *out*.

## Decision

Forbid a `table=True` ORM model as a route's `response_model`, shipped as the
ADR-0006 two-layer pair.

1. **Runtime (fail-closed — the guarantee).** `create_app` validates every module
   router *before* it is mounted: for each `APIRoute` it unwraps the
   `response_model` annotation — through `Page[...]` / `list[...]` and pydantic
   generic models alike — and raises `BootError` if any referenced class is a
   persisted model (a `SQLModel` subclass with a mapped `__table__`, i.e.
   `table=True`). The app refuses to boot, so the leak can never reach production —
   even for a table model imported from another package, where a static scan
   cannot follow the symbol. The check walks the **public** `APIRouter.routes`, so
   it does not depend on FastAPI's internal post-`include_router` representation.

2. **Build-time (early, structural).** A new `terp.arch` rule
   `response_model_not_table_model` scans the app / capability tree for
   `table=True` classes and flags any `response_model=` that references one
   (directly or inside `Page[...]` / `list[...]`). It joins `_ALL_RULES` — so it
   runs over the example app and every capability — and pairs with the runtime
   control, giving a fixable file/line message without needing a boot.

The blessed shape is unchanged: return a `*Read` schema (`BaseSchema`) listing
exactly the safe fields. "Is this a table model?" is centralized in one
`_is_table_model_class` AST helper shared with `table_models_use_base_table`, so
the two rules cannot drift on what "persisted" means.

**Update (2026-06-25, review hardening):** the runtime guard now walks **nested,
included routers** (`router.include_router(...)` keeps the sub-router as a private
`_IncludedRouter`, not a flat route), so a table model exposed on a sub-router is
caught too; and the build-time rule additionally flags
`build_crud_router(read_schema=<table model>)` (ADR 0023), keeping the two-layer
pair total for the factory path.

## Consequences

- `Page[User]` — and `response_model=User`, `list[User]`, … — is now rejected both
  at boot and by the harness; a password hash cannot leak through a mis-declared
  response model.
- The example app and all capabilities already return `*Read` DTOs, so the
  escape-hatch budget stays `{}`: the rule encodes the existing convention rather
  than forcing new work, and is green on day one.
- The runtime layer is strictly stronger than the static one (it also catches a
  model inferred from a route's return annotation and a model defined in another
  package), as a fail-closed control should be.

## Alternatives considered

- **Build-time only.** Rejected: a capability can expose a table model defined in
  another package (e.g. `users` returning identity's `User`), which an AST scan of
  the consuming tree cannot resolve — only the runtime check, holding the real
  classes, closes that. Per ADR 0006 a build-time test is never the only control.
- **Runtime only.** Rejected: the harness is the fast, pre-boot feedback an agent
  gets; dropping it loses the fixable file/line message and the dogfood signal.
- **Allow a table model when `response_model_exclude=` is set.** Rejected as a
  footgun: exclusion lists drift and fail *open* the moment a new sensitive column
  is added. A distinct `*Read` DTO is an allow-list and fails closed.
