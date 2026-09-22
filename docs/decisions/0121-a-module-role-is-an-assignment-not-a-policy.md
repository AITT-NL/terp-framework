# 0121 — A per-module role is an assignment, not a policy

- **Status:** Accepted and implemented. Every phase this record's plan sequenced has landed —
  the declarations, the table and the resolver seam, the guard change, the operator command, the
  HTTP writer, the viewer and assignment surfaces, and the three static rules. What remains is a
  release step rather than a design one: the rules run ahead of their published catalog entries
  under [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md), and the phase
  record is
  [per-module-access-design-and-plan.md](../internal/drafts/per-module-access-design-and-plan.md).
- **Date:** 2026-09-02
- **Relates:** [ADR 0016](0016-permission-in-policy-enforced-as-grant.md) (a permission in a
  policy is a real grant, and `min_role` is a floor), [ADR 0089](0089-granting-is-an-operator-command.md)
  (granting is an operator command, and why least privilege loses to a ten-second workaround),
  [ADR 0102](0102-route-operations-are-declared.md) (a route declares what it does — the
  staging pattern this reuses, and the reason a permission viewer exists at all),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (capability vs
  usage pattern vs legibility — the axis this decision turns on),
  [ADR 0074](0074-groups-capability-and-subject-expansion.md) (a group is a subject; groups
  carry permissions, not roles), [ADR 0004](0004-typed-principal-role.md) (one typed role on
  the principal), [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the role
  model is the app's, not the framework's)

---

## Context

The ask was for the per-module permission editor and viewer a production application has —
*these are the roles, and this is what each role gets in this module* — in the `terp-admin`
area every Terp app already ships.

Most of the surface already existed. `Policy` declares a module's posture and the boot
validates it. `Grant` records that a subject holds a permission, idempotently and audited,
with an FK-less subject so a user, a service account and a group are all grantable the same
way. Subject expansion makes a grant to a group effective for its members. ADR 0102 gives
every route a source-language sentence, which is what lets a viewer say *"Delete a note"*
instead of `DELETE /api/v1/notes/{note_id} write role:editor`. `build_access_graph_for_app`
already assembles the whole guarded surface as data and reconciles it against
`app.openapi()`, so a mounted route cannot hide from it. Studio already renders a module ×
role matrix from that graph.

What did not exist is the fact the editor is *for*. **Terp cannot express "editor in one
module, viewer everywhere else."** A user carries exactly one integer rank; a group carries
none at all — the groups capability says so in as many words, that it carries "permissions,
not roles … a group never changes anyone's rank". The kernel guard reads that one rank, and
reads it *before* it consults any grant, so a grant can never lift a caller over a rank
floor; ADR 0089 §4 names the consequence and `terp grant add` warns about it on the spot.

The result is ADR 0089's own economics one level up. To let someone write in one module you
either raise their rank everywhere — the ten-second workaround that beats least privilege —
or you redesign that module in code so its write requirement is a `Permission` with a
`VIEWER` floor. The first is what people actually do. The second has to be decided per
module, in advance, by someone who can read the source.

Two further facts shaped the decision. Nothing in this repository declared a single named
`Permission`, and the only `require_permission` call site was a docstring example: the
fine-grained half of the model was real, enforced, tested, and unused. And on a scaffolded
app running `PermissionModel.default()` with `Policy.default()`, *every* row of a module ×
role grid is identical — viewer reads, editor writes, admin writes — so the grid asked for
carries almost no information until something makes the rows differ.

## The decision

**Which rungs exist and what each may do is code. Who holds which rung in which module is
data.** The pane assigns; it does not author.

1. **A per-module role is an assignment.** It is persisted as its own fact — subject,
   module, rank — shaped like `Grant` and keyed by the same FK-less `subject_id`, so a
   group's per-module role comes for free through the existing expansion seam with no new
   machinery.

2. **It is additive, and resolves to `max`.** The effective rank in a module is the highest
   of the caller's global rank and every module-role rank over the expanded subject set.
   There is **no per-module deny, ever.** This is the load-bearing half of the decision: a
   system in which authority can be subtracted somewhere is a system in which no pane can
   honestly answer "why can this person do that?", and being able to answer that is the
   only defence an administrator has against an over-broad grant.

3. **An administrator may not compose a role.** Creating a rung, moving a floor, changing
   what a rung grants, or scoping a grant is a code change that rides the agent, the gate
   and a reviewable diff. This is the option the ideology forbids rather than merely
   disfavours: it would hand the authoring of a security boundary to someone the framework
   explicitly assumes cannot evaluate a security trade-off, with no diff and no gate, and
   it would be a second way to say what a `Policy` already says.

4. **What a rung grants is derived, never declared** — from the module's `Policy`, the
   route-level `require_permission` markers, and the declared operations. There is nothing
   to keep in sync, and no way for a module to describe itself inaccurately. To make that
   true rather than merely intended, **the guard's decision becomes a pure function that
   both the guard and the projection call**: today `_endpoint_json` picks the read-or-write
   requirement by testing the method itself and `build_guard` picks it again independently,
   which is exactly the two-copies shape ADR 0102's phase 1.1 had to repair after the
   copies "had already drifted into a reachable privilege-tier escape". The viewer must
   replay enforcement, not describe it.

5. **A module does not participate until it says so, and the platform's own modules say
   they never will.** The default is today's behaviour, global rank only. Opting in is one
   greppable declaration. `users`, `groups`, `access` and `audit` declare that they are
   never per-module grantable, because per-module `admin` in the wrong module is a
   privilege-escalation path — `admin` in `users` provisions users and `admin` in `access`
   grants anything to anyone. Because the default is not-grantable, a new capability that
   forgets to think about this is safe by omission rather than dangerous by omission.

6. **Assigning a module role is an in-app administration surface; granting a permission
   stays an operator command.** ADR 0089's three costs — an admin token, a UUID, an
   undiscoverable string — are why granting sat on the CLI. None of them applies to an
   administrator picking a declared rung for a named person inside the admin area. Its
   rejection of "infer grants from module specs automatically" stands untouched: this
   derives only the *explanation* of a rung, never who holds one.

7. **A declaration that a person reads carries a label, staged not required.**
   `Permission` gains a `label` — one sentence saying what holding it buys — because
   ADR 0102 gave every route a sentence for a reader who cannot translate an HTTP verb and
   a permission has exactly the same reader. It is optional on the constructor and gated by
   a new `LabelCoverage` (`OFF` / `WARN` / `STRICT`), the same three states and the same
   staging as `OperationCoverage`, because requiring it outright would break every existing
   call site for a field nothing renders until the pane exists.

8. **Both write paths to the grant table agree.** `POST /api/v1/access/grants` validates
   the permission against the app's declared catalog, the check `terp grant add` has made
   since ADR 0089. It answers with the catalog in the error `details` rather than only in
   prose, because its caller is a permission editor and a machine-readable list of the valid
   choices is what lets it offer them.

## Why this axis

ADR 0111 separates three things a platform can constrain, and the separation decides this.
Per-module authority is a **capability**: there is something applications need that the
framework cannot do, and no amount of declaration makes it possible. Runtime role
composition is a **usage pattern**: the framework already has a way to say what a rung
means, and a second one is a cost with no benefit. Module labels and permission labels are
**legibility**: restrictions on silence, which remove nothing an application can do.

So the capability gap is closed, the usage pattern is not opened, and the silence is
restricted. That is the whole shape of the decision.

## Consequences

- Least privilege becomes the cheap option for the first time: narrowing someone to one
  module stops requiring either a global promotion or a code change.
- A module × role grid starts carrying information, because rows can differ.
- The kernel gains one seam (`module_rank_resolver`) on the ADR 0016 pattern, and refuses
  the boot of an app that declares grantable modules without installing it.
- The `access` capability gains one table and stops being purely name-keyed.
- Every module role is auditable through the existing write chokepoint, and a stale one —
  naming a rung or a module the app no longer declares — is *shown*, not hidden, on the
  same reasoning ADR 0089 gives for `terp grant list`.
- Studio's viewer and the app's pane render from one builder: Studio reads the declaration
  from source at design time, the pane reads it plus the assignments at runtime.

## Alternatives rejected

- **Administrators compose roles at runtime** (a role table, or bundles of permissions
  ticked in the pane). Refused under decision 3.
- **Materialise an assignment into individual `Grant` rows.** `Grant`'s own docstring is
  right that a row is "a single, immutable fact"; mixing derived rows into the table that
  holds authored ones means nothing can tell them apart afterwards, no viewer can explain
  why a permission is held, and a change to the declaration needs a reconcile job over
  existing data that can fail silently.
- **Use groups as the bundle instead of a new table.** A `Group` already *is* a named
  subject whose grants its members inherit, so bundles need no table and no migration —
  genuinely cheaper. Rejected because it does not close the capability gap: a bundle of
  grants still cannot lift a subject over a module's rank floor, so per-module elevation
  stays unreachable. It also makes the editor's unit N ticked permissions rather than one
  rung, which is the decision an administrator cannot reason about.
- **Derive everything and add nothing.** Honest, and it is what Studio's read-only viewer
  already does, but it leaves the incentive to widen a rank exactly where it was, and it
  answers the ask with a legend for code rather than a control.
- **Fold a scope axis into the matrix** ("editor here, but only for these projects").
  Refused for now: it makes one cell mean two different things. Terp's answer to *where* is
  the scope-predicate registry (ADR 0017) and object authority (ADR 0029).
- **Require `Permission.label` outright.** Refused under decision 7: a required field ahead
  of its only reader is the ceremony "no field without a reader" exists to prevent.
- **Gate the access capability's own write routes on a permission it owns.** Refused: the
  route that creates grants would itself require a grant, and the first administrator on a
  fresh deployment has none. That bootstrap moment is why ADR 0089's out-of-band seam
  exists.

## Open questions

1. Should `LabelCoverage.STRICT` become the default, as strict operation coverage did? The
   same question, deliberately not answered here — and `LabelCoverage`'s own docstring says
   so rather than asserting a destination nobody recorded.
2. Does a per-module `admin` rung mean anything for a module whose `Policy` only
   distinguishes read from write? Rendering the rung as a no-op with a reason, or trimming
   the ladder per module to the rungs that actually differ; the second is more honest and
   more work.
3. Is the ladder per app or per module? Per app is what exists. ADR 0099's name-a-consumer
   test says per module waits for a consumer.
4. Where does tenancy sit? For a `tenant_scoped` module, is a module role per tenant?
   Today `subject_id` is tenant-agnostic. Not answered, but not foreclosed — the assignment
   table's unique constraint may want a tenant column from the start.
5. A route can enforce a permission the control plane never declared, because
   `require_permission` accepts a `str` and constructing a `Permission` does not register
   it. That makes ADR 0089's "can only ever offer permissions this app really enforces"
   stronger than the code guarantees. The fix is a boot check in the same validation pass as
   the declarations.
