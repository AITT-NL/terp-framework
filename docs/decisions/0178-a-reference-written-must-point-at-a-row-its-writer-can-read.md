# 0178 — A reference written must point at a row its writer can read

- **Status:** Accepted and implemented (2026-10-06). `BaseService._save` checks every
  single-column reference a write sets against the target model's row scope
  (`terp.core.scoping.refuse_out_of_scope_references`). Held by
  `tests/architecture/test_reference_scope.py`.
- **Date:** 2026-10-06
- **Relates:** [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) (the row scope
  this applies to writes), [ADR 0133](0133-a-reference-declares-what-a-delete-of-its-target-does.md)
  (the reference declaration), [ADR 0029](0029-object-level-ownership-authorization.md) (the
  write chokepoint's other per-row check), [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md)
  (the open per-tenant role question), [ADR 0071](0071-runtime-role-privilege-split.md)
  (row-level security as a possible later tier)

---

## Context

Tenancy is a row scope (ADR 0017). `TenantScopedMixin` registers a predicate, and every read
through `BaseService` composes it, so a tenant's queries never return another tenant's rows.
`TenantScopedService.create` stamps the tenant from context rather than from the request.
Reads and the stamp were covered. References were not.

A reference is a pointer, and a write sets it to whatever id it is given. A row in tenant A
could be created with a reference to a row in tenant B. The database's foreign key checked
that B's row existed, and it did. Nothing checked that A could see it. For an app whose data
is a graph (nodes, and connections between them), that is one tenant's connection pointing
into another tenant's graph, written through the ordinary service with no error. Soft delete
has the same gap, more quietly: a new row could point at a row the read scope already hides
from everyone.

The scope was always the definition of what a writer can see. The write path never asked it.

## Decision

**A reference a write sets must point at a row its writer can read.** The write chokepoint
(`_save`) looks up each reference the write sets under the target model's row scope
(`apply_row_scope`: soft delete, then every registered predicate, tenancy included):

- **Which references.** On a create, every one. On an update, only the ones it changed. An
  untouched pointer to a row that was soft-deleted since does not block an unrelated edit; a
  new pointer to it is refused.
- **How it fails.** An out-of-scope target fails exactly as a missing one does: the same
  `ConflictError`, a 409 with the same words the database's own refusal produces. Another
  tenant's id and an id that never existed are indistinguishable to the caller, so the refusal
  is not an oracle for which rows exist elsewhere. The real reason travels only in
  `log_context` (`reference_out_of_scope`, the column, the target), which is never sent to
  the client.
- **What it leaves to the database.** A target model with no scope trait, where the scope adds
  nothing the foreign key does not already check (no query is made for it). A table no model
  maps. A multi-column foreign key, which `Ref` never declares.
- **Where it runs.** Inside the write unit, so a refused update rolls back the change it
  carried, and with autoflush off, so the check does not flush the very write it is checking.

**It is the kernel's rule, not the tenancy capability's.** The kernel already owns "what a
reader can see" without importing tenancy. A write that holds to the same definition needs no
tenancy import either, and it covers every scope at once: tenancy, soft delete, and an app's
opt-in owner read scope (`register_owner_read_scope`). A writer that is not itself tenant-scoped
(a bookmark table pointing at tenant-scoped nodes) meets the target's scope too, and outside any
tenant context it can reference no tenant's row.

## Consequences

**A write that pointed out of scope now fails.** It always pointed at something its author
could not read. An app that relied on it (a seed linking rows across tenants, say) sets the
right tenant context for each write. One extra indexed lookup per changed reference to a scoped
model. Nothing for an unscoped one.

**This is the first of the tenancy gaps, not the last.** Each of these is its own decision:

- **The database layer for this rule.** A `Ref` between two tenant-scoped tables could emit a
  foreign key on `(tenant_id, id)`, which needs a unique key on the target and, for
  `SET NULL`, PostgreSQL's column-list form. This ADR is the runtime half. The schema half
  changes DDL for every tenant-scoped reference and needs a migration story.
- **Reads that skip the predicate.** The session re-applies the scope to single-model selects
  and `get`, but not to multi-entity selects, joins, `execute` or lazy loads (STATUS.md's
  open "raw-query isolation" item). The candidates are SQLAlchemy loader criteria, and
  row-level security as the backstop ADR 0071 already names.
- **Memberships and per-tenant roles.** A user has one global role, and access, groups, users
  and audit administration have no tenant column, so an `ADMIN` in one tenant administers all
  of them. Whether one user belongs to several tenants, and how a tenant administrator differs
  from a platform administrator, are product decisions. ADR 0121 left "is a module role per
  tenant?" open, and every grant written widens the migration that answers it.
- **The tenant on audit events.** `AuditEvent` records no tenant, so the trail cannot be read
  per tenant. A small change, best made together with memberships.
- **A tenant registry.** The tenant is a bare UUID with no table behind it, and nothing creates
  or suspends one.
