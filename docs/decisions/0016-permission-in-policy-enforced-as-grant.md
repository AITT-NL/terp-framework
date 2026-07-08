# 0016 - Permission-in-Policy enforced as a real per-subject grant

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0002](0002-control-plane-and-auditable-module-authority.md)
  (the control plane + typed authority), [ADR 0004](0004-typed-principal-role.md)
  (the typed `Principal` role + rank guard), [ADR 0014](0014-adversarial-review-hardening.md)
  (the review this continues). Finding: **H1** in
  [docs/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

The kernel guard (`build_guard`) authorized purely on role **rank**:
`principal.role.rank < required.min_rank`. Because
`AuthorizationRequirement.from_permission` sets `min_rank = permission.min_role.rank`,
a `Policy(write=Permission("invoices.approve", min_role=EDITOR))` collapsed to **"any
editor may write"** — the permission *name* was never consulted at the guard. The
fine-grained, per-subject check (`access.require_permission`) was a *separate, opt-in*
route dependency that an author had to remember to add. So a typed, rule-passing
policy created a false sense of fine-grained authorization (H1): the named permission
was decorative, and forgetting `require_permission` left the action gated only by a
coarse role tier.

## Decision

A `Permission` in a `Policy` is now **enforced as a real per-subject grant**, never
silently degraded to a rank, through an injected enforcement seam — keeping the
kernel free of any capability import.

1. **`PermissionEnforcer` seam (core).** A callable
   `(session, subject_id, permission_name) -> bool` that `create_app` accepts
   (`permission_enforcer=…`, alongside `audit_sink` / `event_dispatcher`) and threads
   into `build_guard`. The access capability supplies the concrete implementation,
   `terp.capabilities.access.enforce_permission` (a thin wrapper over
   `AccessService.has_permission`); core never imports the capability.

2. **`min_role` is an explicit rank *floor*, the grant is mandatory.** For a
   permission requirement the guard now requires the caller to **clear the
   `min_role` rank floor *and* hold the named grant** (via the enforcer). So
   `Permission(min_role=VIEWER)` is effectively grant-only (the floor is trivially
   met), while a higher floor adds a coarse role gate on top — a strict superset of
   the old behavior, and the permission name now *always* gates access.

3. **Fail closed at boot.** `create_app` raises `BootError` if any module `Policy`
   declares a permission requirement but no `permission_enforcer` is installed —
   the misconfiguration is caught at composition time, with a message pointing at
   `terp.capabilities.access.enforce_permission` or a role tier
   (`Policy(write=EDITOR)`).

4. **Fail closed at runtime.** The guard denies a permission requirement when the
   enforcer is absent (defensive, even though boot prevents it) or when the grant is
   missing. The guard reads the grant on the **request session** it injects
   (lazy and FastAPI-cached, so it is the same session the handler uses); a role-only
   route never issues that query.

5. **Two-layer, with conformance tests.** The runtime guard enforcement + the
   boot-time validation are paired with tests: `build_guard` unit calls (allow /
   deny-without-grant / deny-below-floor / deny-without-enforcer / role-read-path),
   `create_app` boot (fail without enforcer, boot with), and an HTTP end-to-end
   (`403` before the grant, `200` after).

`access.require_permission` remains for **route-level** checks layered on top of (or
instead of) the policy-level gate; this ADR makes the **policy-level** `Permission`
gate real.

## Consequences

- A `Policy` permission requirement is now genuine fine-grained authority at the
  kernel guard; the access capability is consulted automatically, so an author can no
  longer believe a permission is enforced while it is only a tier.
- A consumer using **only role tiers** is unaffected (no enforcer required, no boot
  failure, no per-request grant query).
- The example app now wires `permission_enforcer=enforce_permission` (dogfood), and
  its end-to-end suite was switched to the ADR-0015 `WriteGuardedSession`, so the full
  reference composition exercises the write guard too.
- 305 tests, 100% framework line coverage.
- **Still open (sequenced):** H2 (non-overridable `base_query` scope predicate), H3
  (forbid a `table=True` `response_model`), and first-class tenancy/role wiring
  (H7/H8). A first-class **object-level / ownership** authorization seam is recorded
  as a new backlog item (the per-row complement to this per-permission gate).
