# 0074 — Groups capability and the access subject-expansion seam

- Status: accepted
- Date: 2026-07-06
- Decision drivers: the packaged admin area needs a real "groups" surface; per-user
  grants do not scale past a handful of users; the single-role ladder (ADR 0004) must
  stay untouched; the access capability must stay a leaf (ADR 0013's boundary logic).

## Context

Terp's authorization stack has two grain sizes: the kernel `Policy` guard (one role
rank per principal, ADR 0004) and the access capability's per-subject permission
grants (ADR 0016). There was no way to say *"these twelve users may export
reports"* short of twelve grants — and nothing an admin UI could present as the
familiar "groups" concept. `Grant.subject_id` was deliberately FK-less ("the
principal may be non-user"), anticipating collective subjects without ever having
one.

## Decision

1. **A new `terp-cap-groups` capability** owns `user_group` / `user_group_member`
   tables (names avoid the reserved `GROUP` keyword), an audited `GroupsService`,
   and a self-registering, admin-only router at `/api/v1/groups` (CRUD +
   membership). `user_id` is FK-less exactly like `Grant.subject_id`; `group_id`
   is a real FK (both tables live in the package). Memberships are immutable rows
   (add / remove), unique per (group, user). It ships its own linear Alembic
   history (`terp.migrations` entry point `groups`).
2. **Groups carry permissions, never roles.** Granting to a group is an ordinary
   access grant whose `subject_id` is the group's id — no new grant table, no
   parallel authorization model, and the role ladder is untouched.
3. **The access capability gains a subject-expansion seam**
   (`terp.capabilities.access.expansion`): a registered `SubjectExpander` maps one
   subject to the extra subject ids it speaks for. `AccessService.has_permission`
   / `permissions_for` — the single hot path behind both `require_permission` and
   the kernel guard's `permission_enforcer` — check the **expanded** set. The
   plug-in direction mirrors the scope-predicate registry (ADR 0017): access owns
   the registry and the check; groups registers its membership expander at package
   import (entry-point discovery imports it, so *installing* the capability is the
   whole wiring); access never imports groups.
4. **Expansion is flat.** Groups do not nest: a group id expands to nothing. One
   indexed membership query per permission check.
5. **Deleting a group cascades atomically.** Inside the same write unit
   (ADR 0038), the group's membership rows are `_remove`d and its grants revoked
   through the access service — every step audited, the whole cascade one
   transaction — so a dangling group id can never keep authorizing former members.
6. **Groups joins the base profile.** The example app's `_BASE_CAPABILITIES`, the
   template's default dependencies, and therefore the baked `@terp/contract`
   schema now include it: every generated app has `/api/v1/groups` and group-aware
   permission checks out of the box.

## Alternatives considered

- **Multi-role principals / role groups** — rejected: changes the kernel's
  single-role contract (ADR 0004) and every guard comparison for a need that is
  permission-shaped, not rank-shaped.
- **A `group_id` column on `Grant`** — rejected: access would need to know about
  groups (inverted dependency), and every future collective subject would need
  another column. The FK-less subject id already models this.
- **Expansion at grant-write time** (copy the group's grants to each member) —
  rejected: membership changes would fan out into grant rewrites (unbounded,
  unauditable as one intent), and revocation on member removal becomes a
  reconciliation job. Expansion at check time is one indexed query and always
  current.

## Enforcement

| Control | Runtime (fail closed) | Build time |
|---|---|---|
| Group-aware checks | `has_permission` queries the expanded subject set; a raising expander propagates (denies) | `tests/architecture/test_groups.py` (member allowed, outsider refused, removed member refused; failing expander propagates) |
| Audited mutations | all writes ride `_save` / `_remove` | groups is in `_CLEAN_CAPS` (full arch scan, zero opt-outs); audit-order tests |
| Atomic cascade | cascade runs in the group delete's write unit | rollback test (a failing cascaded write leaves group, members and grants intact) |
| Admin-only surface | `Policy(read=ADMIN, write=ADMIN)` behind the deny-by-default guard | e2e: editor 403, anonymous 401 |
| Schema drift | per-package Alembic history + boot guard (ADR 0027) | migration conformance suite; `test_openapi_contract` pins the base profile |
