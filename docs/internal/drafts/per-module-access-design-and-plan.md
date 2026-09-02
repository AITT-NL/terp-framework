# Per-module access — design notes and the sequenced plan

> **Decision:** [ADR 0112](../../decisions/0112-a-module-role-is-an-assignment-not-a-policy.md) —
> §3's fork is settled as option (A), the model is code and the pane assigns. This file is now the
> execution tracker; when it disagrees with the ADR, the ADR wins.
>
> **Status:** phase 1 and phase 2a shipped. **Audience:** platform/core team + agents.
>
> §9 records a three-design panel run against this plan and the four mechanisms adopted from it.
> Its adversarial judges did **not** run, so no design here has been independently scored.

The ask, in one line: give a Terp app the per-module permission editor and viewer that an existing
production application has — *these are the roles, and this is what each role gets in this module* —
built for the framework's abstract, modular shape rather than ported from a codebase whose module
list is an enum, and shipped in the `terp-admin` area every app already gets.

The short answer to "can we add this to the default admin module": **yes, and that is the right
home** — but the pane is the last of five pieces, not the first. Most of the surface already exists
in some form; the one genuine gap is not a UI gap at all. It is that Terp cannot currently express
"editor in one module, viewer everywhere else", which is the fact the whole editor is *for*.

---

## 1. What Terp already has

Worth stating precisely, because most of the surface is built and the temptation is to design over
the top of it.

| Piece | Where | What it gives us |
|---|---|---|
| Typed role ladder + named permissions | `terp/core/permissions.py` | `Role(name, rank)`, `Permission(name, min_role)`, one validated `PermissionModel` per app |
| Declared module posture | `terp/core/module_spec.py` | `Policy(read=…, write=…)`, deny-by-default, boot-validated against the control plane |
| Permission grants | `terp/capabilities/access` | `Grant(subject_id, permission)` — one immutable fact, FK-less subject, idempotent, audited |
| Subject expansion | `access/expansion.py`, `groups/expander.py` | a grant to a *group* is effective for its members, with no extra call sites |
| What each route *does*, in plain language | `terp/core/operations.py` (ADR 0102) | `OperationDefinition(id, label)` per route, no-drift-checked, localizable |
| The whole access surface as data | `terp/cli/access.py` → `build_access_graph_for_app` | roles, permissions, per-module policy, per-route requirement + operation, data traits, and fail-visible warnings/omissions |
| A discoverable write path for grants | `terp/cli/grants.py` (ADR 0089) | `terp grant add/revoke/list`, validated against the app's own catalog |
| A read-only permission matrix | terp-studio `PermissionsView.tsx` + `accessMatrix.ts` | module × role matrix, already rendering `none / read / write / …-grant / public / unknown` |
| The admin area itself | `react-core/src/admin/` | `AdminHub`, users, groups, group detail, user detail, audit |

Two of these deserve emphasis. `build_access_graph_for_app` already reconciles the graph against
`app.openapi()` and reports any mounted route the graph does not cover under `omitted_routes` — so
the platform can already say, honestly and mechanically, "this is the whole guarded surface".
And ADR 0102 exists precisely so a permission view can say *"Verwijder een bestand"* rather than
`DELETE /api/v1/files/{file_id} write role:admin`. The input data for a legible pane is already
declared and already gate-checked.

## 2. What is actually missing

**2.1 Per-module authority cannot be expressed.** A user carries exactly one integer rank
(`UserCreate.role: int`, resolved against the app's `PermissionModel` at login). A group carries
none at all — `groups/models.py` says so in as many words: *"Groups carry permissions, not roles …
a group never changes anyone's rank."* The kernel guard reads that one rank:

```python
if principal.role.rank < required.min_rank:
    raise PermissionDeniedError()
```

`terp/core/app.py:205`. The check runs **before** the grant check, so a grant can never lift a
caller over a rank floor — ADR 0089 §4 names the consequence and `terp grant add` warns about it on
the spot. The result is the exact economics ADR 0089 was written about, one level up: the only way
to let someone write in *one* module today is to raise their rank everywhere, or to convert that
module's write requirement to a `Permission` with a `VIEWER` floor and grant it. The first is the
ten-second workaround that beats least privilege; the second works but has to be designed per
module, in code, in advance.

This is a **capability** gap in ADR 0111's sense, not a usage-pattern gap, which is why it is worth
spending a decision on: there is a thing applications need that the framework cannot currently do.

**2.2 A module cannot say what it is called or what it is for.** `ModuleSpec` carries `name` (an
identifier), `policy`, `services`, `requires`, `emits`, `subscribes`, `jobs`, `tenant_scoped` and
`max_request_bytes`. There is no human label and no summary. The reference application solves this
with a hand-maintained frontend registry of module labels, descriptions and icons, kept honest by a
drift test against a backend enum. We should not copy that: we should make the module answer the
question itself, which deletes the registry and the drift test together. This is a legibility
declaration in ADR 0111's sense — a restriction on silence, which costs no capability.

**2.3 The access graph has no runtime reader inside the app.** It is built for a CLI and consumed
out-of-band by Studio. An app's own admin pane cannot see it.

**2.4 The packaged admin frontend hardcodes the ladder.** `react-core/src/admin/roles.ts` returns
ranks `10 / 20 / 30` as literals. ADR 0022 makes the backend role-model-agnostic; the frontend
admin is not. An app with a four-rung ladder gets a three-rung admin UI today. Any matrix built on
top of this inherits the bug, so it has to be fixed first.

**2.5 There is no editor anywhere.** Grants are written by CLI (ADR 0089) or by the admin-only
`POST /api/v1/access/grants`. Neither has a UI, and the HTTP one does not validate the permission
against the declared catalog the way the CLI does — a typo is accepted and stored as a silent no-op.

**2.6 The permission vocabulary has two incompatible shapes.** Found while checking what the pane
would have to render. `Permission.name` must be a dotted token, and the validator rejects anything
else:

```
notes.write     OK
a.b.c           OK
reports:export  ValueError: Permission.name must be a dotted token
billing:write   ValueError: Permission.name must be a dotted token
```

(Run against `terp.core.permissions` in the repo venv.) But the access capability's own docstrings
teach the colon form as the example — `access/models.py` offers `"billing:write"` and
`"reports:export"` as what permissions look like, and `access/deps.py` shows
`require_permission("reports:export")`. `Grant.permission` is an unvalidated `str`, so the colon
form can be *granted* while being impossible to *declare*: it can never appear in a `Policy`,
`terp grant add` will refuse it as unknown, and `terp grant list` will report it `[stale]`. Since
the arch rule `no_adhoc_permission_literals` pushes authors onto the typed path anyway, the fix is
to correct the docstrings — but a pane that renders permission names cannot present a vocabulary
with two mutually exclusive shapes, so this is in the way and belongs in phase 1.

**2.6b The agent-facing guide taught a form the gate refuses.** The same class of defect as §2.6,
found while adding the label to `terp guide permissions`, and worse because of where it lived. Both
the `policy` and `permissions` topics showed the route-level check as
`dependencies=[Depends(require_permission("invoices.approve"))]` — a bare string literal, which is
exactly what the `no_adhoc_permission_literals` architecture rule exists to refuse. The `policy`
topic even said "Authority is always a typed object (Role / Permission), never a bare string" four
lines below its own counter-example.

This matters more than the docstring in §2.6 did. The guide is the surface an agent reads first, and
under the ideology a machine-readable failure message and a fix recipe are the framework's primary
interface — so a recipe that produces a violation is not a typo, it is the interface being wrong.
Fixed to pass the declared constant, with the rule named in the line so the reason travels with it.

**2.7 Named permissions have no consumer anywhere in the repository.** This is the finding that
most shapes the recommendation, so it is worth being exact about. Searching `apps/`, `template/`
and every capability for a `Permission(...)` declaration returns **nothing**, and searching for a
`require_permission(...)` call site returns exactly one hit — the docstring example in
`access/deps.py:11`. Neither the example app nor the template declares a single named permission;
both pass `PermissionModel.default()`, which is the bare `viewer < editor < admin` ladder with an
empty permission tuple.

ADR 0089's context says of grants that "almost nobody uses them". That is true inside the framework
too, and it has a consequence for this design: the fine-grained half of the authorization model is
real, enforced and tested, but it has no consumer. ADR 0099's name-a-consumer test is the house
standard, and applying it honestly here says the pane should be built over the primitive
applications actually reach for — the ladder — rather than over the one that exists but is unused.

It also means the example app currently has nothing a per-module pane could show. Phase 5 has to
add a genuinely grantable module to it, or the feature ships undemonstrable.

**2.8 A route can enforce a permission the control plane never declared.** Found while adding
the catalog check to the grants endpoint, and deliberately *not* fixed there. Two facts
combine: `require_permission` accepts a `str` as well as a typed `Permission`, and
constructing a `Permission` object does not register it — only membership in
`PermissionModel(permissions=…)` does. So a route may require `reports.export` while the
control plane declares nothing of the sort, and nothing refuses that at boot.

The consequence lands on ADR 0089, which says the grant command "can only ever offer
permissions this app really enforces". That is the intent, but the code guarantees the
converse and not the claim: everything offered is declared, while something enforced may be
undeclared — and is then unreachable through the sanctioned write path, because `terp grant`
and now the endpoint both refuse it.

**Closed in phase 2b**, as a boot check in the same validation pass as the declarations, which
is where it was deferred to. It is unconditional, like the no-drift half of every other
catalog: what is tunable elsewhere is *coverage* — whether a declaration may be declined —
never whether a declaration that exists has to resolve.

The first thing it caught was the example app's own `gated_app` test fixture, which enforced
`widgets.write` as a literal against an empty control plane: the exact shape described above,
in this repository, in the file that teaches `require_permission`. The fixture now declares
the permission and claims it on the spec.

**2.9 A policy could cite a same-name authority at a different rank, and did not have to say
so.** Found by reviewing the work above rather than by reading the original code, and fixed
immediately because it is a privilege discrepancy rather than a tidiness one.

`Policy` keeps the rank floor of whichever object it is handed — `AuthorizationRequirement.from_role`
and `from_permission` read it straight off — while `ControlPlane._policy_errors` only checked that
the *name* was registered. Every view reports the floor the control plane declares. So
`Policy(read=Role("admin", rank=1))` booted clean, admitted every viewer, and was displayed as
admin-only; measured, not reasoned:

```
boot errors: ()
enforced floor: 1 (declared admin is 30)
```

The permission form is the same defect with a `min_role`: a module citing
`Permission("invoices.approve", min_role=VIEWER)` against a control plane declaring it at `ADMIN`
enforced rank 10 and reported rank 30. Studio's matrix would have shaded that column from the
declared floor, so the pane would have disagreed with the guard — exactly the failure this whole
design exists to make impossible, sitting in the code the design was going to build on.

Authority turned out to be the *only* control-plane registry matched by name alone. Events, jobs
and operations are each matched **by value**, and all three docstrings name this exact hazard —
accepting a same-id definition "would let a route present one wording while the catalog documents
another". An authority shadow is that with a rank attached, which is why it earns a boot error
rather than a warning. `PermissionModel.shadowed_requirements` reports it separately from an
undeclared reference, because the two have different fixes.

**The rule is narrower than "the ranks differ", and the narrowing is the point.** A first pass
flagged every rank mismatch, and that refused a configuration ADR 0022 explicitly blesses: every
bundled capability pins `Policy(read_role=Roles.ADMIN)` at rank 30, so an app declaring its own
`admin` at 40 would have been unable to mount the framework's own routers. With no role occupying
30–39 those two floors are the same gate by different numbers. So a shadow is reported only when
**some declared role sits in the gap** — which is precisely when the policy admits or refuses
someone the declaration does not. Add a `manager` at 35 to that same app and it is refused, because
the capability router would then let a manager into an admin-only surface. That case was silent
before, in a ladder shape the framework encourages.

## 3. The fork

**The decision to make: who is allowed to change what a role means?**

- **(A) The model is code; the pane assigns.** Which rungs a module has, and what each rung may do,
  is declared in the application's source and changed by asking the agent — which produces a
  reviewable diff and passes the gates. The pane lets an administrator say *who* holds *which rung*
  in *which module*, and explains what that buys.
- **(B) The model is data; the pane composes it.** An administrator can also create roles and tick
  the operations they include, at runtime, in the pane.
- **(C) Viewer only.** Improve the read-only matrix; leave every write to the CLI and the agent.

**Recommended: (A).**

(B) is the one option the ideology rules out rather than merely disfavours. It hands the authoring
of a security boundary to someone the framework explicitly assumes cannot evaluate a security
trade-off, with no diff, no gate and no review — and it creates a second way to say what a `Policy`
already says. It is also the option that cannot be undone: once role composition is data, every
later gate has to accommodate a model no static check can see.

(C) is honest but does not answer the ask, and it leaves 2.1 unfixed — which means it leaves the
incentive to widen a rank in place.

(A) is what the reference application actually implements, once you look past the UI: its ladder is
three fixed rungs declared in code, and its editor writes *assignments* of a rung to a subject per
module. The nice pane is a pane over assignment, not over policy.

**The engineering fork inside (A): how does an assignment become an effective decision?**

- **(A1) Materialise.** Assigning a rung writes the individual `Grant` rows it bundles.
- **(A2) Resolve.** The assignment is its own row; the guard resolves it at request time.

**Recommended: (A2)** — because `Grant`'s docstring is right that a row is "a single, immutable
fact: subject holds permission". A1 mixes derived rows into the table that holds authored ones, and
after that nothing can tell them apart: no viewer can explain *why* someone holds a permission, and
a change to the declaration in code needs a reconcile job over existing data that can silently fail.
A2 keeps the declaration authoritative — change what `editor` means in a module and every existing
assignment follows on the next request — and makes provenance computable, which is the property the
whole viewer depends on.

## 4. The recommended design

### 4.1 A module declares that it is grantable, and what it is called

Secure by default: **a module does not participate in per-module assignment unless it says so.**
The default is the current behaviour — global rank only. Opting in is one declaration, and it is
greppable.

```python
module = ModuleSpec(
    name="notes",
    router=router,
    services=(NotesService,),
    requires=("access",),
    permissions=(NOTES_DELETE_PERMISSION,),
    access=ModuleAccess(
        label="Notes",
        summary="Free-form notes, with deletion held behind a named grant.",
        assignable=True,
    ),
    policy=Policy.default(),
)
```

*(Shipped in phase 2b-ii, with one naming change from this section as first written.*
`ModuleAccess.grantable(...)` *would have collided with the field it sets, and ADR 0112's own
sentence is "a per-module role is an **assignment**", so the field is* `assignable` *and the only
classmethod is the refusal —* `ModuleAccess.platform_only(reason=...)` *— exactly the shape*
`Policy` *uses, where the ordinary case is constructed directly and the justified exception gets a
named constructor.)*

That is the whole authoring surface, and it is deliberately *not* a per-rung permission table: what
each rung may do is **derived** (§4.3), so there is nothing to keep in sync and no way for a module
to describe itself inaccurately. The rungs are the app's own ladder from `PermissionModel`, so a
four-rung app gets four rungs with no further declaration.

The platform-administration modules must refuse assignment explicitly, because per-module `admin`
in the wrong module is a privilege-escalation path — `admin` in `users` provisions users, and
`admin` in `access` grants anything to anyone:

```python
access=ModuleAccess.platform_only(
    reason="administering grants is the platform's own authority, not a per-module role",
)
```

`users`, `groups`, `access` and `audit` ship with that declaration, each with its own reason.
Because the default is absence, a new capability that never considered the question is safe by
omission rather than dangerous by omission — and one test asserts that *none* of the four is
missing, which is the property that matters rather than any one of them individually.

A module label needs no coverage knob, unlike a permission's. The requirement is a **constructor
invariant** instead: an assignable `ModuleAccess` with no label raises. That is free where a
permission's was not — the field is new, so there are no existing call sites to break — and it is
the stronger control of the two, since it cannot be staged off. A module cannot ask to appear in
an editor and decline to say what it is called.

**Two additions from the design panel (§9, design A), both adopted.** A named permission is
currently orphaned in two ways this design would otherwise have had to work around:

- **It belongs to no module.** *(Shipped in phase 2b.)* `Permission(name, min_role)` sat in one
  flat app-level tuple, so a route-level `require_permission` extra had no module row to appear on
  except by parsing its dotted prefix — a convention no gate enforces, and one that says nothing
  at all about a permission two modules share. Design A's mechanism is better than guessing from
  the name: the module *claims* its permissions on the spec,
  `ModuleSpec(permissions=(NOTES_DELETE_PERMISSION,))`, standing to `PermissionModel` exactly as
  `emits=` stands to the `EventCatalog` — the module lists typed objects, the app registry declares
  them, and boot cross-checks by value. That is the repository's established no-drift shape, already
  used three times (events, jobs, operations), so it costs no new pattern. The by-value half also
  catches the *label* shadow that `shadowed_requirements` cannot see, since an
  `AuthorizationRequirement` carries only a rank floor. The access graph now emits the edge, so a
  module row and its permissions resolve without inference.
- **It has no human label.** `OperationDefinition` carries one because ADR 0102 was written for a
  reader who cannot translate `DELETE /api/v1/files/{file_id}`; a permission has exactly the same
  reader and no such field. So `Permission` gains a `label` — one sentence saying what holding it
  buys — which is what the editor puts next to a row it is asking someone to tick.

**Shipped, and not as first written.** This section originally called for making `label`
**required**. That was wrong on the repository's own terms: there are 28 live `Permission(...)`
call sites, nothing renders a label until phase 5, and "no field without a reader" cuts against
imposing a required field ahead of its consumer — ADR 0099's name-a-consumer test says the
consumer is phase 5, not now.

So it ships the way ADR 0102 already stages exactly this requirement: `label` is optional on the
constructor, and a new `LabelCoverage` (`OFF` / `WARN` / `STRICT`, the same three states and the
same reasoning as `OperationCoverage`) decides whether an unlabelled declaration is tolerated,
reported, or refused at boot. `OFF` is the framework default for the reason ADR 0102 gives about
its own flip — turning it on before declarations carry labels refuses the boot of every app that
has any. Whether `STRICT` becomes the default is an open question, not a decision this section
gets to make (ADR 0112). The example app runs `STRICT` from the start, because
the app whose job is to demonstrate the control is the wrong place to leave it off.

`LabelCoverage` is named for one thing rather than two on purpose: phase 2's module labels want the
same staging, so the enum has a second consumer waiting rather than being a general-purpose knob
invented for one.

### 4.2 What is persisted

One table, in the `access` capability, shaped like `Grant` for the same reasons:

```python
class ModuleRole(BaseTable, table=True):
    __tablename__ = "access_module_role"
    __table_args__ = (UniqueConstraint("subject_id", "module", name="uq_access_module_role"),)

    subject_id: uuid.UUID = Field(index=True)     # FK-less, exactly like Grant.subject_id
    module: str = Field(max_length=64, index=True)
    role_rank: int = Field(index=True)
```

`subject_id` being FK-less is what makes groups work with **no new machinery**: a group's id is a
subject, and the existing subject-expansion seam already maps a user to their groups. Per-module
roles for groups come for free the day the table exists.

Additive by construction, and only additive: the effective rank in a module is

```
max(global rank, every module-role rank over the expanded subject set)
```

There is no per-module *deny*. That is the decision that keeps the viewer explainable — a system
where authority can be subtracted somewhere is a system where no pane can honestly answer "why".

Two disciplines carry over from `terp grant`, and both are load-bearing rather than tidy:

- **A write validates the rank and the module against the declaration, and refuses.** An assignment
  naming a rank the app's ladder does not declare, or a module that is not grantable, is not a
  lenient assignment — it is a row that can never fire, or worse, one that fires somewhere nobody
  intended. `PermissionModel.role_for_rank` already fails closed on an unregistered rank, so the
  refusal has a natural home. This is ADR 0089's "there is no `--force`" applied to the new table.
- **A stale row is shown, not hidden.** If the app later drops a rung or stops declaring a module
  grantable, the stored assignment is exactly the thing an administrator needs to find and clean
  up. `terp grant list` already marks such entries `[stale]`; the pane and the CLI do the same here
  rather than silently filtering them, because a filtered row is an unexplainable right.

### 4.3 What is derived, and never declared

The cell content — *what does this rung get in this module* — is computed from data that already
exists and is already enforced:

- the module's `Policy` read/write requirement, per HTTP method, as the kernel guard chooses it;
- each route's `require_permission` marker, which `terp.core.routing.required_permission` already
  exposes;
- each route's `OperationDefinition`, which supplies the plain-language label;
- the model traits and registered predicates, which supply the honest caveats (`read_scope`,
  `write_authority`, and the graph's existing warnings).

`build_access_graph_for_app` already assembles all of it. So the explanation cannot drift from
enforcement, because it *is* the enforcement data — the same property the reference application gets
by deriving its rollup from live route gates, reached here without a second endpoint to maintain.

**One correction to that claim, from the design panel (§9, design C) — shipped in phase 3.**
"It is the enforcement data" was true of the *inputs* and false of the *reasoning*. `build_access_graph`'s `_endpoint_json` picks
the read or write requirement by testing the method against `MUTATING_METHODS` itself, and
`build_guard` picks it again independently — two copies of the same decision, which is exactly the
shape that produced the drift ADR 0102's own phase 1.1 had to fix ("the copies had already drifted
into a reachable privilege-tier escape"). So the projection adopts design C's mechanism: the guard's
decision becomes a pure function

    decide(policy, method, rank, holds_permission) -> Decision

that **`build_guard` and the projection both call**. The viewer then does not describe enforcement,
it replays it, and a change to the rule can only change both at once. This is the single most
valuable idea the panel produced and it is adopted wholesale.

Two things the implementation added that the sketch did not carry:

- **The permission check is a callable, not a `bool`.** The guard has always issued the grant
  query only when a permission requirement is actually reached, so a role-only route never
  touches the database. An eagerly-evaluated argument would have moved that query onto every
  guarded request in the framework. A test counts the calls, because a signature says nothing
  about *when* it is invoked.
- **A route-level `require_permission` is folded into the per-rung answer.** `decide` answers
  for the module `Policy`, which is the only authority the kernel guard applies; a route-level
  dependency is a second requirement the policy does not carry. Replaying only the guard
  reported an editor as *allowed* on the example app's `DELETE /notes/{id}` — a route an editor
  without the grant gets a 403 from. That was caught by reading the projection's output, and it
  is precisely the pane-disagrees-with-the-gate failure this section exists to prevent, so the
  extra requirement is folded in and such a rung is reported `grant` instead.

The projection now carries `by_role` per endpoint — one entry per declared rung with the
outcome and its reason slug — so whatever renders the matrix stops re-deriving allowance from
rank comparisons. That is what makes the duplication genuinely gone rather than merely
consolidated on the server: `accessMatrix.ts` computes today what the server can now state.

Two honesty rules carry over, and both are already latent in the graph:

- Counts and lists cover **module-gated routes only**. A public or kernel route belongs to no
  module, so the wording is "module operations", never "everything".
- A module whose routes declare no operation is reported as unexplained rather than rendered with
  guessed labels — which is `OperationCoverage.STRICT` doing its job, and a reason to finish it.

### 4.4 The introspection surface

The graph becomes readable inside the app, admin-only, from the data already on `app.state`:

```
GET  /api/v1/access/model            -> the declared model: ladder, permissions, modules, per-rung outcomes
GET  /api/v1/access/subjects/{id}    -> one subject's effective access, with the provenance of every right
GET  /api/v1/access/operations/{id}  -> who can perform this operation, and how
POST /api/v1/access/preview          -> the delta a proposed assignment would produce, committing nothing
```

*(`/model` shipped in phase 3, admin-only and typed end to end — the DTOs are not ceremony but
the pane's types, since the frontend contract is generated from this app's OpenAPI document
(ADR 0041). The other three need the assignment rows or the subject seams, so they move to
phase 4 with the machinery they depend on.)*

`/model` is derivation over `app.state` with no database read, so it is cacheable per boot. It is
served over `terp.core.authz.build_access_model`, which is where the shared projection now lives:
the access capability cannot import `terp.cli`, so the alternative to moving it was a second
projection — the thing §4.3 exists to prevent. `terp inspect access` composes that same builder
with the parts only an audit wants (model traits, registered predicates, kernel and schema-hidden
routes, undeclared subscribers, and the reconciliation against `app.openapi()`), and a test pins
the boundary in both directions so the two cannot drift back together.
`/subjects/{id}` is the one that must carry **provenance**: every right comes back tagged with where
it came from — global rank, a module role held directly, a module role held through a named group, a
permission grant held directly, a permission grant through a named group — plus the scope and
ownership caveats that narrow it. A viewer that shows the effective answer without the provenance
is the failure mode to avoid: it tells an administrator that something is wrong without telling them
where to fix it.

`POST /preview` exists so the pane can show the delta before committing, using the same code path
that computes the answer afterwards, rather than a second implementation that can disagree with it.

**The layering constraint on the reverse lookup, and the better answer.** "Who can perform this
operation" wants to answer with *names*, but the `access` capability deliberately cannot see them:
its whole premise is that `subject_id` is FK-less so it stays a leaf the identity and app modules
depend on, never the reverse. Reaching into `users` from `access` would invert exactly that;
`terp grant`'s lazy in-function imports of `UsersService` are the CLI's own exception and are not a
precedent for the capability.

This plan first proposed returning bare subject ids and letting the pane resolve the names itself.
The design panel (§9, design A) found the better shape, and it is adopted — two additive seams in
the direction the repository already sanctions, where a lower layer owns a registry and a higher
layer plugs into it at import time (ADR 0017's scope predicates, and the existing
`register_subject_expander`):

- **`SubjectExpander` returns an attributed `SubjectRef`, not a bare `UUID`.** The groups capability
  already answers "which subjects does this caller speak for"; it simply throws away *why* on the
  way out. Returning `(id, kind, name)` lets a report say "via the group Engineering" while
  `subject_ids_for` keeps projecting plain ids for the decision, so the hot path is unchanged and
  the provenance the whole viewer rests on stops being something the pane has to reconstruct by
  cross-referencing a second and third request.
- **A `SubjectDirectory` seam** lets `access` name one subject and enumerate the holders at a rank
  without importing identity — the same plug-in direction, filled by whichever capability owns
  users.

The second is what makes the reverse lookup answerable at all rather than merely renderable: a pane
resolving ids client-side can only name subjects it has already listed, so "who can perform this
operation" would silently omit service accounts, or any subject the pane had not fetched.

Writes stay on the existing admin-only surface, extended to assignments and — this is a bug fix, not
a feature — validated against the declared catalog the way `terp grant` already is, so an HTTP grant
of an undeclared permission is refused instead of stored as a silent no-op.

### 4.5 The pane

In `react-core/src/admin/`, so every app gets it: `/admin/access` for the model, and an access panel
on the existing user and group detail screens for assignment. Localised through the framework
catalog (ADR 0105), never hardcoded strings.

Most of it composes from what `react-core/src/ui` already ships — `Card`, `Badge`, `Tooltip`,
`Button`, `ConfirmDialog`, and `Radio`, which is the radiogroup the tier strip is underneath its
styling. One genuinely new component is needed: a group of selectable tiles, each carrying a label
and a body, behaving as one radiogroup with **manual activation** — arrows move focus, Space or
Enter commits — because automatic activation would fire the top rung's confirmation while the
administrator is merely arrowing past it. That passes ADR 0099's test: it can name its consumer
here and now, and nothing in the inventory does the job.

**The viewer** answers four questions, and they are four lenses rather than four screens:

1. *What does each role get in this module?* — the module list, one row per grantable module, each
   row carrying the ladder. This is the reference application's best idea and it is worth taking
   deliberately: **the whole ladder is visible at once as a strip of tiles, not a dropdown.** A
   dropdown hides the options and makes two rungs impossible to compare. "No access" is a real
   tile, so revoking is exactly as reachable as granting. And the rhetoric is inverted from the
   subscription-plan shape it borrows: no recommended rung, no badge on the top tile, and the
   destructive count carries the visual weight — the pane should bias *down*.
2. *What does moving up a rung actually hand over?* — the delta, "everything in the rung below,
   plus …", split by kind rather than as one flat list, because "may delete three things" is a
   different decision from "may read thirty" and a mixed list buries the destructive half.
3. *What can this person do, and why?* — effective access with provenance, on the user detail
   screen. A group-inherited rung is shown as a **floor** on the tier strip, so the rung actually in
   force is marked rather than implied by the direct assignment alone.
4. *Who can do this?* — the reverse lookup, per operation.

**The editor** is the same strip, made interactive, on a user or a group: pick a rung per module,
see the delta, commit. The top rung confirms. Editing your own account is refused. A module that
declares `platform_only` renders locked with its reason, rather than being silently absent — the
reason is the useful part.

Studio's own `PermissionsView` stays read-only and keeps its "ask the agent" affordance. The
division is cleaner than it first looks, and it falls out of how the two consumers already get
their data:

- **Studio is design-time.** It runs `terp inspect access --app` in a subprocess
  (`terp_studio/introspect.py`), booting the project's app to read what the *source* declares. No
  database, no assignments — it works before the app has ever been deployed, and it shows what the
  code says. Changing that means changing code, which is why its affordance is "ask the agent".
- **The app's admin pane is run-time.** It reads the same builder off `app.state`, plus the
  assignment rows, and shows who actually holds what today.

One builder, two consumers, no second source of truth — the same discipline `terp inspect access`
already keeps by being "a view, never a second source of truth" (ADR 0011).

### 4.6 Enforcement, on both sides

Backend: one new seam on `create_app`, mirroring `permission_enforcer` from ADR 0016 —
`module_rank_resolver(session, subject_id, module_name) -> int` — filled by the access capability
and never imported by the kernel. `create_app` already builds one guard per spec inside its mount
loop (`app.py:1651`), so the module name is in scope at the call site and only has to be passed
through; the change is otherwise confined to the rank comparison:

```python
rank = principal.role.rank
if module_rank_resolver is not None:
    rank = max(rank, module_rank_resolver(session, principal.id, module_name))
if rank < required.min_rank:
    raise PermissionDeniedError()
```

The module ranks deliberately do **not** go on `Principal`. That type is identity plus one role by
design (`app.py:100`), and a map of module ranks hung off it would have to be resolved eagerly on
every request, for every module, including the ones the request never touches. The resolver is
consulted lazily by the one guard that needs it, on the request session the handler already holds —
the same shape `permission_enforcer` uses, and for the same reason.

Permission requirements keep their existing grant check unchanged, so the two mechanisms compose
without overlapping: **per-module rank is coarse module authority (what the pane edits); permission
grants stay fine-grained extras (what `terp grant` edits).** Neither is a second way to do the
other's job.

Fail closed at boot, on the ADR 0016 pattern: an app whose modules declare `ModuleAccess.grantable`
but which installs no resolver refuses to boot, with a message naming the resolver.

Frontend: the same rule has to apply there or the control is half-built — a module the caller can
reach only through a per-module rung must appear in the sidebar and render its write controls. The
pieces are already parallel to the backend's, which is what makes this small:

- `Action` is `"read" | "write" | "admin"` (`contract/src/auth.ts:28`) and `useCan(action)` compares
  rank, exactly as the guard does. It needs the module in scope to apply a module rung. A module
  manifest already declares the module for every route and nav entry, so the module can be
  **inferred from the active route** by default, with an explicit override for a screen that shows a
  control belonging to a different module. Inference is the agent-proof default: nothing to
  remember, and a forgotten override hides a control the user is entitled to rather than exposing
  one they are not.
- `/me` already carries the caller's permission names for display (`usePermissions`, ADR 0096). It
  grows the module ranks alongside them, under the same framing that file already states plainly:
  a display input, never authority, because the server re-checks every request.

### 4.7 The gates, and the mutation each must fail on

| Gate | Mutation that must go red |
|---|---|
| Boot refuses `grantable` without a resolver | remove the resolver from the example app's `create_app` |
| Guard honours the module rung | make the resolver return `0`; a per-module-editor request must 403 |
| Assignment is additive only | make the resolver `min` instead of `max`; a global admin must lose nothing |
| `platform_only` refuses assignment | drop the flag from `access`; assigning `admin` there must stop being refused |
| HTTP grant validates the catalog | remove the check; an undeclared permission must stop being refused |
| Frontend reads the app's ladder | restore the hardcoded `10/20/30`; a four-rung app must render four rungs |
| Sidebar honours module rank | drop the module rank from the frontend rule; the reachable module must vanish |
| Provenance is complete | remove the group branch from the resolver; a group-derived right must lose its "why" |
| Label coverage under STRICT | remove one label; the boot must refuse |

Every row is an assertion about behaviour rather than about shape, which is what makes the list
mutation-checkable at all. None of them is satisfiable by a fixture whose values coincide with the
expected output.

## 5. The plan, in phases that each end somewhere shippable

1. **Cleanups that stand alone**, none of which need any of the design below:
   - [x] the access capability's docstrings stop teaching a permission shape the typed path
         rejects (§2.6), and the colon form is now pinned as rejected in
         `test_role_and_permission_reject_bad_tokens`.
   - [x] the example app declares its first named permission, `notes.delete`, in a real
         `control_plane/permissions.py`, and `DELETE /api/v1/notes/{id}` requires it on top of
         the module's write tier — closing §2.7 for the example app and, incidentally, making
         `control_plane/operations.py`'s docstring reference to that file true.
   - [x] `POST /api/v1/access/grants` validates against the declared catalog the way
         `terp grant` already does (§2.5), returning the catalog in the error `details` so a
         permission editor can offer the valid choices rather than asking someone to retype a
         name it has already rejected.
   - [x] `roles.ts` reads the app's declared ladder instead of the `10 / 20 / 30` literals
         (§2.4). Deferred to phase 3 and landed there, because the honest fix needed a source
         for the ladder and that source is the introspection endpoint — doing it in phase 1
         would only have traded hardcoded literals in one file for a hardcoded default in
         another. `UserCreate`'s `useState("10")` was the second half of the same defect.
2. **The declarations** — all of it declaration-only, so nothing changes behaviour yet:
   `ModuleAccess.grantable` / `platform_only` on `ModuleSpec` with labels, boot validation and
   `OperationCoverage`-shaped label coverage; `ModuleSpec(permissions=(…))` cross-checked against
   `PermissionModel` by value; a required `label` on `Permission` (§4.1, breaking, with this
   repository's one call site updated in the same commit); and the boot check §2.8 defers here —
   every permission named at a route is declared — since it is the same validation pass. The
   platform capabilities get their `platform_only` declaration in this phase, before anything can
   assign a rung.
3. **`decide()` and the introspection endpoints.** Extract the guard's decision into the pure
   function `build_guard` and the projection both call (§4.3) — a refactor with no behaviour change,
   provable by the existing guard tests — then serve the model from `app.state`.
   `terp inspect access` and Studio keep working off the same builder, and `roles.ts` finally has a
   source for the ladder, so phase 1's remaining item lands here. Ends shippable: a real viewer with
   no writes.
4. **`ModuleRole` + the resolver seam + the guard change.** Per-module authority becomes real and
   enforced, with the CLI (`terp module-role add/list/revoke`) as the first writer — an operator
   seam before a UI, on the ADR 0089 pattern. Ends shippable: the capability exists and is auditable.
   - [x] The table, the service, the seam, the guard change and the boot refusal. §2.1 is closed.
   - [x] The CLI writer over `validate_assignment`'s three refusals, plus a fourth for an
         unknown role name that prints the app's own ladder. `terp grant`'s subject resolution
         moved to a shared `_subjects.py` rather than being copied — ADR 0089's argument is
         that the UUID stops being the interface, and two commands drifting on that would put
         the cost straight back.
   Two properties turned out to need a specific fixture to observe at all, and a mutation found
   both. `max` over the expanded subject set reads as obviously right but is indistinguishable
   from `min` while there is one row per subject per module — which the unique constraint
   guarantees — so only a subject holding one rung directly *and* another through a group can
   tell them apart. And "a module role never lowers a global rank" cannot be observed by a
   caller whose global rank already clears the floor, because the resolver is never consulted
   for them; the fixture has to be an admin holding the *lowest* rung in the module.
5. **The pane**, viewer lenses first, then assignment. Template and example app pick it up — and
   the example app needs a second grantable module whose rows genuinely diverge from `notes`, or the
   first screenshot of this feature is three identical columns (§9, design C).
6. **terp-spec rules and the violation corpus**, once the declarations are stable. The catalog
   already has the precedents to copy — `backend/modules_declare_policy` for a required module
   declaration, `backend/routes_declare_operation` for a coverage-gated one, and
   `backend/policy_refs_resolve` for a reference that must resolve against the control plane. Three
   new rules, each in that shape, each with a corpus fixture:
   - `backend/grantable_modules_are_named` — a module that opts into per-module assignment answers
     what it is called and what it is for, because the pane renders that text to an administrator
     who cannot read the source. Coverage-gated, like `routes_declare_operation`.
   - `backend/platform_modules_refuse_module_roles` — a module that administers the platform's own
     authority declares that it is not per-module grantable, with a reason. Required, not gated:
     this is the privilege-escalation guard from §4.1.
   - `backend/module_role_writes_go_through_the_capability` — no module reads or writes the
     assignment table directly, on the same footing as `no_manual_ownership_checks`.

Phases 1–3 change no authorization behaviour at all, which is worth having: most of the visible
value arrives before anything can go wrong at runtime.

## 6. Decisions to record

- ~~**A per-module role is an assignment, not a policy.**~~ **Recorded as ADR 0112**, together with
  the additive `max` rule, the not-grantable default, the platform-module refusal, the derived
  explanation and the shared `decide()`, the operator-command boundary, the staged label, and both
  write paths agreeing. Its five open questions are the live ones; §8 below is now a duplicate of
  that list and defers to it.
- **Per-module authority is additive and resolves to `max`.** No per-module deny, ever.
- **A module is not grantable until it says so, and the platform's own modules say they never are.**
- **What a rung grants is derived, never declared.** Amends ADR 0102's boundary note: the operation
  catalog gains a second consumer, and this is the one it was written for.
- **Granting a *permission* stays an operator command; assigning a *module role* is an in-app
  administration surface.** ADR 0089 needs an explicit note saying which of the two it governs. Its
  three named costs — an admin token, a UUID, an undiscoverable string — none of which apply to an
  administrator picking a declared rung for a named person in the admin area.
- **ADR 0089's rejection of "infer grants from module specs" stands.** This design derives only the
  *explanation* of a rung, never who holds one. Who may do what still requires someone to say so.

## 7. Deliberately not in scope

- **Scoped grants** — "editor in this module, but only for these projects". The reference application
  keeps this on a separate surface and so should we; Terp's answer is the scope predicate registry
  (ADR 0017) and object authority (ADR 0029), and folding a *where* axis into the matrix would make
  the cell mean two different things.
- **Recertification, access campaigns and usage-based pruning.** Real, and a later decision.
- **Per-operation assignment in the pane.** The rung is the unit an administrator can reason about;
  per-operation ticking is (B) wearing a different hat.
- **Time-boxed or approval-gated assignment.** ADR 0095's fenced custody is the nearer relative;
  not now.

## 8. Open questions

The decision's own open questions live in
[ADR 0112](../../decisions/0112-a-module-role-is-an-assignment-not-a-policy.md) and are not
repeated here — two copies of one list is how a list rots. They are: whether strict label
coverage becomes the default; whether a per-module `admin` rung means anything for a module
whose policy only distinguishes read from write; whether the ladder is per app or per module;
where tenancy sits; and the undeclared-route-permission hole from §2.8.

One question belongs to the build rather than the decision, so it stays here:

1. **How does the preview endpoint stay honest under concurrency?** The delta is computed
   against state that can change before the commit. Optimistic concurrency on the assignment
   row is the obvious answer and matches the users capability's existing `version` discipline.

## 9. The design panel, and what it changed

**What was actually run, and what it does not establish.** Seven readers mapped the subsystems (the
reference application's editor UI and its authorization backend; Terp's backend authz seams, its
binding ADRs, and its admin frontend; terp-spec; terp-studio), and three agents each designed the
whole surface from a *different assigned stance*: (A) the model is a declared artifact and the pane
edits only who holds what; (B) roles are runtime-composable bundles over a declared vocabulary;
(C) nothing new is declared and the matrix is derived. Three adversarial judges and a synthesis pass
were also queued and **did not run** — they died on a session limit. So what follows is three
independent designs, not a verdict: nothing here has been adversarially scored, and §3's fork has
not been externally reviewed.

The stance assignment also has to be read carefully. Each design's concessions are partly artifacts
of the stance it was told to defend, so their agreement is weaker evidence than it looks. What is
worth noting is narrower and still useful: **none of the three delivers per-module elevation, and
each says so in its own terms.** A concedes an administrator cannot "move a floor". B leaves the
rank comparison at `app.py:205` untouched by design and refuses an ordered ladder over bundles.
C states that a principal holds exactly one global role and a grant has no module column, so
"nothing on a module × role grid is an assignment". That is §2.1 restated three ways, which is why
the fork in §3 and the recommendation stand unchanged.

**Four mechanisms adopted**, each better than what this plan had:

1. **The guard's decision becomes a pure function both the guard and the projection call** (C, §4.3).
   This plan claimed the explanation "is the enforcement data"; that was true of the inputs and
   false of the reasoning, since `_endpoint_json` and `build_guard` each pick the read-or-write
   requirement independently. The viewer should replay the decision, not describe it. The most
   valuable single idea the panel produced.
2. **A module claims its permissions on the spec** (A, §4.1) — `ModuleSpec(permissions=(…))`
   cross-checked against `PermissionModel` at boot, exactly as `emits=` is against the event
   catalog. Better than deriving a permission's module from its dotted prefix, which no gate
   enforces.
3. **`Permission` gains a `label`** (A, §4.1). ADR 0102 gave every route a sentence for a reader who
   cannot translate an HTTP verb; a permission has the same reader and had no such field.
4. **`SubjectExpander` returns an attributed ref, and a `SubjectDirectory` seam names subjects**
   (A, §4.4). Replaces this plan's weaker answer — bare ids resolved client-side — and is what makes
   the reverse lookup answerable rather than merely renderable.

**The one genuine alternative to §4.2, and why it is still not preferred.** Design B observed that a
runtime bundle of permissions is *already persisted*: a `Group` is a named subject, and granting to
it is an ordinary grant (ADR 0074), so composable bundles need **no new table and no migration** —
materially cheaper than the `access_module_role` table in §4.2. It is a real finding and it should be
on the record. It is still not the recommendation, for two reasons. It does not solve elevation: a
bundle of grants cannot lift a subject over a module's `Policy` rank floor, so "editor in notes for
a viewer" remains unreachable unless every module's write requirement is redeclared as a
`Permission` with a `VIEWER` floor — a per-module redesign in code, which is the thing an
administrator was supposed to be spared. And it makes the editor's unit wrong: "editor in notes"
becomes N ticked permissions rather than one rung, which is precisely the decision an administrator
cannot reason about and the reference application's tier strip exists to collapse.

**Design C's sharpest critique, which is about the ask itself.** For a scaffolded app on
`PermissionModel.default()` and `Policy.default()`, *every* module row of a module × role grid is
identical — viewer reads, editor writes, admin writes — so the grid carries almost no information
and the real content sits one level down, at the operation rows. This is correct, and it is the best
argument in the whole panel *for* §4.2 rather than against the request: what makes the rows differ
is a per-module assignment that the framework cannot currently express. Without it the pane is a
legend for code; with it the pane is the control the ask describes. It is also a warning about
phase 5's demo — the example app needs at least two modules whose rows genuinely diverge, or the
first screenshot of this feature will show three identical columns.

**One idea considered and refused.** Design A gates the access capability's own write routes on a
declared permission it owns (`access.grants.write`), so the feature names an in-framework consumer.
Refused on bootstrap grounds: the route that creates grants would itself require a grant, and the
first administrator on a fresh deployment has none. ADR 0089's out-of-band operator seam exists for
exactly that moment. §2.7 is answered instead by the example app's `notes.delete`, which has a real
consumer and no bootstrap cycle.

