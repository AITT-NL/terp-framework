# 0014 - Adversarial-review hardening of the secure-by-construction guarantees

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), after an adversarial design review
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the quadruple + two-layer enforcement), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)
  (the audited write chokepoint), [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md)
  / [ADR 0012](0012-actor-stamping-trait.md) (auto-honored traits),
  [ADR 0013](0013-users-capability-and-identity-boundary.md) (the users surface).
  Full findings: [docs/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

A red-team review of the "secure / audited / correct **by construction**" thesis
found that the two headline guarantees leaked **silently** in real use:

1. **"All persistence flows through one audited chokepoint"** was false in the
   framework's own capabilities. `TenantScopedService.create`, `AccessService.grant`,
   and `AccessService.revoke` wrote raw to the session (`session.add` / `delete` +
   `commit`) instead of `BaseService._save` / `_remove`, so tenant-scoped creates
   and **RBAC permission changes — the most audit-sensitive events — emitted no
   audit record**. Capabilities were never arch-scanned, so the
   `mutations_emit_audit` rule never saw them.
2. **"An agent cannot ship the common insecure patterns"** was weaker than claimed:
   the `mutations_emit_audit` rule matched only four hard-coded session variable
   names and four verbs, so renaming the variable (`s.add(...)`) or smuggling a
   write through `session.execute(update(...))` / `text(...)` evaded both the rule
   and the audit trail.

The review also found: relative `from ..sibling import x` evaded
`no_cross_module_imports` (absolute-only); the admin surface had no last-admin /
self-lockout protection (an admin could deactivate or demote the last admin and
lock everyone out of the admin-only routes, unrecoverable without raw DB access);
durable audit was opt-in with **no** production guard; and capability discovery
loaded entry points unguarded (one broken capability crashed boot with a bare
traceback, a mistyped entry point vanished silently, and a duplicate name
shadowed a trusted router).

## Decision

Harden each leak as a fail-closed control, keeping the two-layer discipline (a
runtime control **and** a build-time test), and **make the framework dogfood its
own rules** by arch-scanning the capabilities.

1. **Capabilities route every write through the audited chokepoint.**
   `TenantScopedService.create` now stamps `tenant_id` then calls `_save`;
   `AccessService.grant` / `revoke` call `_save` / `_remove`. So tenant creates and
   grant/revoke are audited, actor-stamped, event-hooked, and 409-mapped like every
   other write.

2. **Capabilities are arch-scanned.** A new framework test runs the full `terp.arch`
   harness over every capability package. The only opt-outs are three **governed
   framework primitives**, each carrying a justified `# arch-allow-*` marker under a
   checked-in per-capability escape-hatch budget: the durable audit sink's raw
   `session.add` (it *is* the base of the write stack), the append-only `AuditEvent`
   table (no `version` / `updated_at` by design), and the central tenant predicate in
   `TenantScopedService.base_query` (the very thing the rule points app modules to).
   A drift guard fails if a new capability is added but not scanned.

3. **`mutations_emit_audit` is harder to evade.** The verb set gains the bulk/flush
   writers; a DML write through `execute` / `exec` (`insert` / `update` / `delete` /
   raw `text`, distinguished from a `select` read) is now flagged; and the receiver
   is recognised by any parameter annotated `Session` / `SessionDep`, not only a
   fixed name allowlist — so renaming the session variable no longer evades the rule.
   (A runtime write-guarded session is sequenced as the deeper structural fix.)

4. **`no_cross_module_imports` resolves relative imports** to their absolute module
   before matching, so `from ..sibling import x`, `from .. import sibling`, and
   `from app.modules import sibling` are caught like the absolute form.

5. **`_remove` maps a constraint violation to a uniform 409**, mirroring `_save`, so
   a hard delete blocked by a foreign key no longer leaks a raw 500.

6. **The admin surface protects administrator access.** `UsersService.set_active`
   and `update` refuse to deactivate/demote the last active admin (typed
   `LastAdminError` → 409) and refuse self-deactivation/self-demotion by the
   acting administrator (typed `SelfAdminActionError` → 409). Active-admin rows
   are selected with `FOR UPDATE` where the database supports it, with a
   process-local lock as a second layer, so concurrent admin changes serialize
   instead of racing the invariant.

7. **Production requires a marked durable audit trail.** `create_app` fails to boot
   in production when audit is enabled but no `DurableAuditSink` is installed;
   the escape is an explicit `AuditPolicy.disabled(reason=...)` or the audit
   capability's marked `persist_audit` sink. A placeholder `lambda` no longer
   satisfies the production guard.

8. **Capability discovery fails closed.** `iter_capability_specs` raises a typed
   `CapabilityDiscoveryError` when an entry point fails to import, resolves to a
   non-`ModuleSpec`, or collides on `name`, and `create_app` rejects duplicate names
   across **all** explicit app specs plus discovered capability specs — no
   bare-traceback boot crash, no silent vanish, no router shadowing.

## Consequences

- The audit guarantee is now structural for the capabilities that exist for
  multi-tenant SaaS and RBAC; a future capability that bypasses the chokepoint fails
  the capability arch-scan.
- The three capability opt-outs are visible, justified, and budgeted — they can only
  shrink (the ratchet), exactly like a client app's.
- 282 tests, 100% framework line coverage.
- **Still open (sequenced as their own decisions):** a runtime write-guarded session
  (the deepest fix for write-bypass, replacing name-based AST matching); the
  `Permission`-in-`Policy` guard that silently collapses to a role rank; making the
  `base_query` scope predicate non-overridable; a `response_model` rule/runtime check
  that forbids returning a `table=True` model (password-hash exposure); and a
  first-class `create_app(..., middleware=/tenant_resolver=)` plus tenant-aware login
  so multi-tenancy and custom roles do not require abandoning the bundled stack.
