# 0025 - Medium-severity input & observability hardening (M2/M3/M6/M8)

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile) — adversarial-review follow-ups (medium)
- **Relates:** [ADR 0014](0014-adversarial-review-hardening.md) (the review this
  closes four medium findings from),
  [ADR 0020](0020-response-model-data-leak-guard.md) (the response-model guard M3
  tightens), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the log-only
  audit sink M8 makes legible), and the
  [adversarial design review](../internal/reviews/2026-06-24-adversarial-design-review.md)
  (findings M2, M3, M6, M8).

---

## Context

The [adversarial design review](../internal/reviews/2026-06-24-adversarial-design-review.md)
triaged a set of medium-severity findings. Four of them share a theme — the
boundary controls were *shape/name-scoped* heuristics that an off-convention
input could slip past, or an observability seam that silently dropped data:

- **M2 — input length cap is name/shape-scoped.** `check_input_str_fields_have_max_length`
  only scanned classes ending `Create`/`Update` (or extending `BaseTable`), and
  `_is_str_annotation` matched only `str` / `str | None`. A request-body DTO named
  off-convention (`LoginRequest`, `UserProvision`) or a field typed `list[str]`
  escaped the cap → unbounded-input / request-size DoS.
- **M3 — a `-> None` route can still return ORM data.** The response-model rule
  exempted any handler annotated `-> None`, but Python does not enforce return
  annotations, so `def x() -> None: return note` serialized the ORM object.
- **M6 — over-posting depended entirely on schema narrowness, unchecked.**
  `BaseService.create` did `self.model(**data.model_dump())` and `update` did
  `setattr` per dumped field; a too-wide Create/Update schema could mass-assign a
  framework-managed column (the primary key, `version`, `tenant_id`, the actor
  stamps), and no control audited schema-field safety.
- **M8 — `StructuredFormatter` dropped every `extra=` field.** `format()` emitted
  only `level/logger/request_id/message` (+`exc_info`), so the log-only audit
  sink's `extra={audit_action, …}` never reached the JSON line — hollowing the
  fallback audit trail and general observability.

## Decision

Each fix preserves Terp's **two-layer** rule: a fail-closed runtime control **and**
a build-time `terp.arch` test, never the test alone.

1. **M2 — cap every client-supplied string, by role not by name.** The input-cap
   rule now treats a field as client-supplied when it lives on a table model, a
   `*Create` / `*Update` schema, **or any class used as a request body** — a route
   handler's body parameter, or a `build_crud_router(create_schema=/update_schema=)`
   argument (route correlation, `_request_body_model_names`). A body parameter is
   recognized in every ordinary annotation shape — bare `LoginRequest`, qualified
   `schemas.LoginRequest`, `Annotated[LoginRequest, Body()]`, and `LoginRequest |
   None` / `Optional[LoginRequest]` (`_annotation_type_name`). `_is_str_annotation`
   now also recurses into sequence containers (`list[str]`, `tuple[str, …]`,
   `Sequence[str] | None`), so a collection of strings must cap too. `dict` is
   deliberately excluded — `max_length` is the wrong bound for a mapping.

2. **M3 — exempt only no-body responses, not `-> None`.**
   `check_routes_declare_response_model` now exempts a route when it declares a
   no-body `status_code` (204/205/304), not when it is annotated `-> None`. A
   handler that omits both a `response_model` and a no-body status is flagged, so a
   `-> None` annotation can no longer launder an ORM object out of the boundary. The
   rule covers **both** decorator routes (`@router.get(...)`) and imperative
   registration (`router.add_api_route(...)`, the form `build_crud_router` itself
   uses), and the no-body status is recognized as a literal **or** a conventional
   named constant (`status.HTTP_204_NO_CONTENT`, `HTTPStatus.NO_CONTENT`).

3. **M6 — managed columns are framework-owned, two layers.**
   - *Build time:* a new rule `input_schemas_exclude_managed_columns` fails any
     input schema — a `*Create` / `*Update` **or** any request-body DTO (the same
     role-based set M2 uses) — that declares a framework-managed column (`id`,
     `created_at`, `updated_at`, `version`, `tenant_id`, `deleted_at`,
     `created_by_id`, `modified_by_id`).
   - *Runtime:* `BaseService.create` / `update` strip that same set from the
     inbound payload (`_without_managed_columns`) before constructing / patching
     the row — so even an over-wide schema or a hand-built dict cannot forge the
     primary key, defeat optimistic concurrency, or cross a tenant boundary.
     `TenantScopedService.create` strips the same set before stamping the
     context-derived `tenant_id`, so a tenant-scoped write is covered identically
     (and the strip also removes a body `tenant_id` that would otherwise collide).
     The two managed-column sets (in `terp.core.base_service` and `terp.arch`) are
     kept in lockstep by construction and pinned by a test.

4. **M8 — emit redacted `extra=` context.** `StructuredFormatter.format` now
   serializes every non-standard `LogRecord` attribute (the `extra=` fields) under
   a nested `"extra"` object. Those fields have already passed through
   `RedactingFilter` on the handler, so secrets are masked before they reach the
   formatter — redaction stays the filter's job, serialization the formatter's. The
   log-only audit sink's `audit_*` context now reaches the JSON line.

## Consequences

- **The boundary heuristics became role-based, not name-based.** An off-convention
  input DTO is now capped and over-posting-checked the same as a `*Create`; new
  capabilities get the protection without adopting a naming convention.
- **Over-posting is closed structurally**, independent of how narrow a schema
  author made the DTO — the runtime strip holds even if the build-time rule is
  ever bypassed (and vice-versa).
- **The fallback audit trail is legible**: with no durable sink installed, the
  structured log line now carries the audit action/target, so H5's
  defense-in-depth fallback is real, not nominal.
- **No behavior change for clean code.** The example app and every shipped
  capability already capped their inputs, declared no managed columns, and used
  no-body 204 deletes, so the gate stays green (347 tests, 100% line coverage) and
  the escape-hatch budget stays `{}`.

The remaining medium/low findings (M4, M5, M7, M9, L1–L5) are product-roadmap or
documentation items tracked in the review and `STATUS.md`, not part of this slice.
