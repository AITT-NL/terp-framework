# 0004 - Typed Principal role (role-model-agnostic enforcement)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase A keystone (close the role-model genericness gap)
- **Supersedes/relates:** [ADR 0002](0002-control-plane-and-auditable-module-authority.md),
  [docs/STATUS.md](../internal/STATUS.md) "Known limitations"

---

## Decision

`Principal.role` is now a typed `terp.core.Role` (name + rank), and the auth
access token carries the role's **name and rank** rather than coercing it to the
three-tier `Roles` enum. Authorization compares ranks
(`principal.role.rank < requirement.min_rank`), so a consumer can define any role
model in its control plane and issue principals bearing those roles.

The legacy `Roles` enum (`viewer < editor < admin`) stays as the **default model
and a back-compat convenience**: a kernel seam `as_role()` normalizes a `Roles`
value to the matching default `Role`, and `Principal` / `create_access_token`
accept either. Existing call sites that pass `Roles.EDITOR` keep working unchanged.

## Problem this closes

Before this change the role vocabulary was hardwired three ways:

- `Principal.role: Roles` — a principal could only ever be viewer/editor/admin.
- `create_access_token(role: Roles)` and `decode` did `Roles(int(payload["role"]))`,
  which **rejected any rank** outside `{10, 20, 30}`.

So a custom `PermissionModel` could be *declared* and boot-validated, but a
principal could not *hold* a custom role — the framework was not actually
role-model-agnostic. (Reviewed and recorded as the #1 known limitation on
2026-06-24.)

## How it works now

- `terp.core.permissions.as_role(value)` — `Role` passes through; a `Roles`
  (`IntEnum`) maps to the matching default `Role` by rank; anything else raises
  `TypeError`.
- `Principal(id, role)` normalizes `role` through `as_role` in `__post_init__`, so
  `principal.role` is always a typed `Role`.
- `build_guard` gates on `principal.role.rank` vs the policy requirement's
  `min_rank` (a higher rank satisfies a lower requirement — tier semantics that
  work for any rank set).
- `create_access_token(role: Role | Roles)` signs `role` (name) + `rank`;
  `decode_access_token` rebuilds `Role(name, rank)` with no enum coercion, so any
  rank round-trips. `AccessTokenClaims.role` is a `Role`.

Proven end to end by `test_custom_role_round_trips_through_the_jwt` (an
`approver` role at rank 25 survives issue -> decode) and
`test_principal_carries_typed_and_custom_roles`.

## Consequences

- The **framework** (kernel + auth) is now role-model-agnostic: declare roles in
  the control plane, issue principals bearing them, enforce by rank.
- **Remaining, smaller nuances** (tracked, not blocking):
  - `Policy.default()` / `Policy.tiers()` still reference the names
    `viewer`/`editor`/`admin`, so an app that *renames* the default tiers must
    declare its own policies rather than rely on the defaults.
  - `Policy.read_role` / `write_role` remained vestigial back-compat projections
    (enforcement uses the typed `*_requirement`); **retired in [ADR 0018](0018-retire-vestigial-policy-role-projection.md)**.
  - The bundled `terp-cap-identity` store still persists the default `Roles` model
    (it stores a rank int and exposes `Roles` in its DTOs). A consumer wanting a
    custom role store supplies its own `authenticate` callback — auth already takes
    one, so this is a capability choice, not a framework limit.
- No migration needed (nothing deployed); the JWT claim shape changed from
  `{role: int}` to `{role: name, rank: int}`.

Status: **Accepted** — 144 tests green, 100% line coverage; the role-model
genericness gap is closed at the framework level.
