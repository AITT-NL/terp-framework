# 0002 - Control plane and auditable module authority

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase A (control-plane spine + centralized permission model)
- **Supersedes/relates:** [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md),
  [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md), [ADR 0001](0001-terp-namespace-and-kernel-scope.md)

---

## Decision

Terp introduces a reserved, top-level `control_plane/` package in consumer apps.
It is the single authority surface for cross-cutting concerns: permissions,
events, realtime topics, audit, security, database configuration, and future
platform-level registries.

The first implementation track is **Phase A** from the implementation plan:

1. Add a typed `ControlPlane` aggregate to `terp.core`.
2. Add a centralized `PermissionModel` with typed `Role` and `Permission` objects.
3. Let `Policy` accept either a `Role` or a `Permission`, normalizing to a typed
   authorization requirement, never a string.
4. Keep module declarations (`policy`, `emits`, `subscribes`, `realtime`) on
   `ModuleSpec` as the single module overview surface.
5. Require every cross-reference to be a typed object. Bare strings are not an
   authority mechanism.
6. Treat security-relevant absence as explicit, justified, and budgeted. Product
   features may be absent silently; controls may not.
7. Build a minimal `terp inspect control-plane` surface early so a remote or paid
   reviewer can inspect the authority map without reading every route.

The control plane is intentionally a central registration surface. This is not a
retreat from module discovery: modules remain discoverable and self-contained,
while authority configuration is centralized so it can be reviewed, diffed, and
audited.

## Confirmed defaults

| Decision | Accepted default |
|---|---|
| Control-plane format | Typed Python modules under `control_plane/`, plus `terp.toml` for pure data |
| Permission model default | The existing `viewer < editor < admin` tiers mapped to named permissions |
| First track after Phase A/B | Security middleware + structured logging |
| Control-plane location | Top-level `control_plane/` package |

## Rationale

The target user may be non-technical and may rely on coding agents. The platform
therefore cannot rely on advice like "remember to use the right dependency" or
"keep permission names consistent." The framework must make drift mechanically
hard:

- A module may reference authority objects from `control_plane/`.
- A module may not define roles, mint permission strings, invent event names, or
  hand-roll realtime topics.
- Boot validation rejects unknown or undeclared references.
- The architecture harness catches local invention and unsafe omissions before
  runtime.

This narrows human review to the durable authority map and the escape-hatch
ledger. It does not prove business intent. A technical reviewer remains part of
the system, but the review surface becomes small, stable, and remotely auditable.

## Consequences

- `control_plane/` becomes a reserved package in templates and client apps.
- `terp.core` grows a typed control-plane and permission-model public surface.
- Existing `Roles` and `Policy.default()` remain compatible during the transition;
  the current three-tier ladder is the default model.
- `terp-cap-access` keeps its existing flat grant behavior initially, then grows
  typed permissions, groups, scopes, and visibility behind the same model in
  Phase B.
- `terp-arch` gains rules that enforce references to the control plane and reject
  ad-hoc authority strings in modules.
- Documentation and progress must stay in repo files, not only in chat:
  [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) carries the design,
  [docs/STATUS.md](../internal/STATUS.md) carries the progress ledger, and this ADR carries
  the accepted decision.

## Implementation checkpoints

Phase A is complete only when all of these are true:

- A default `ControlPlane` and `PermissionModel` boot existing apps unchanged.
- `Policy(read=Role | Permission, write=Role | Permission)` works and normalizes
  to typed requirements.
- `create_app(..., control_plane=...)` validates all module policy references.
- The example app declares a top-level `control_plane/` and remains clean.
- `terp-arch` catches bare authority strings in module manifests.
- `terp inspect control-plane` can print at least roles, permissions, and module
  policy requirements.
- The full gate is green.

Status: **Accepted** - proceed with Phase A.