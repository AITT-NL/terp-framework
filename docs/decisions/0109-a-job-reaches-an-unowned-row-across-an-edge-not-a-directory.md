# 0109 — A job reaches an unowned row across an edge, not a directory

- **Status:** accepted, and built in the same release
- **Date:** 2026-09-01
- **Supersedes nothing.** Narrows the escape route ADR 0029 §8 left open and
  answers the question `_validate_background_jobs_preserve_ownership` has been
  asking in its own error message since it shipped.

## Context

Background work runs without an originating user, so it runs as the control-plane
system actor. That actor is deliberately **not** an ownership bypass: a purge job
must not be able to delete rows a user owns simply because it has no user of its
own. Two checks enforce it, and they are twins:

- **Composition** — `_validate_background_jobs_preserve_ownership` in
  `core/app.py` refuses to boot a `ModuleSpec` that declares `jobs` while one of
  its declared `services` binds a model that is not `OwnedMixin`.
- **Build** — `check_no_manual_ownership_checks` in `arch/rules/traits.py` says
  the same thing over the source tree, and honours a budgeted
  `# arch-allow-no-manual-ownership-checks: <reason>` marker.

Both messages already state, at length and correctly, that the marker clears the
build half only: a comment is gone by the time a class object exists, so an app
that takes the marker passes `terp check` and then cannot start. That asymmetry is
recorded, tested (`tests/architecture/test_jobs.py`) and is not what this record is
about.

What this record is about is the sentence both messages end on:

> Declare the job and the unowned service on different modules, or raise the gap.

### The advice is sound exactly once, and neither check knows the difference

Modules are independent by default (ADR 0087): a sibling import is refused unless
the importing module names the sibling in its own
`ModuleSpec(requires=("other",))`. So splitting a job away from an unowned service
genuinely severs the reach — the job *cannot* call that service — **as long as no
edge is declared between the two**.

Add the edge and the reach is back, in one line, with nothing to stop it. Neither
check follows `requires`:

- the composition twin iterates `spec.services`, which is the module's *own*
  services;
- the build clause matches a `ModuleSpec(jobs=…)` literal and an `OwnedMixin` base
  name **within the same module directory**.

So the platform's own remedy for the gate is also the way through it. A developer
who follows the message to the letter, and then discovers the job needs the
service after all, adds `requires=` — a line that reads like ordinary coupling,
passes every check, and quietly restores exactly the authority the gate exists to
withhold.

That is a gate that reports success without doing the work, which is a species
this codebase has now fixed three times elsewhere. It is worse than the others in
one respect: the failure is *invited by the error message*.

### The build half is a weaker approximation of the composition half

Three limits are recorded as residuals in terp-spec's `RESIDUALS.json`, so they
are data rather than folklore:

1. `jobs=MODULE_JOBS` bound to a name is not seen as declaring background work —
   the clause matches a list or tuple **literal**.
2. `OwnedMixin` reached through an intermediate base, or on a model declared in
   another package, is not recognised — the clause matches a **direct base name**
   in the same module directory.
3. A `ModuleSpec` that omits `services=` is not caught by the composition twin,
   which iterates the declared services.

The composition half has none of the first two: `issubclass(model, OwnedMixin)`
follows the MRO, and it reads real objects rather than a directory. So where the
two disagree, **the app gets green CI and a boot failure** — the worst ordering,
because the cheap check passes and the expensive one fails.

## Decision

### 1. The question is reachability, not co-location

A module's jobs must not reach an unowned CRUD service **through any declared
path**, not merely through its own package directory. Both halves resolve the
declared dependency closure — `declared_dependency_graph` already exists in
`arch/rules/dependencies.py` for `check_no_cross_module_imports`, and `ModuleSpec`
already carries `requires` at runtime — and ask whether any service reachable from
a job-declaring module binds a model that is not owned.

This keeps the legitimate split working and closes the one-line dodge. It also
makes the advice in both messages true for the first time, so it can stay.

### 2. The build half converges on the composition half, not the reverse

Residuals 1 and 2 become bugs and are closed: the clause resolves `OwnedMixin`
through the AST class graph rather than by direct base name, and treats any
non-empty `jobs=` as declaring work (an empty literal and `None` remain "no
jobs"). Residual 3 stays open and is the composition half's to close separately.

The direction matters and was the live alternative. Narrowing the composition
check to match the build check's weaker matching was considered and rejected in
§ "Alternatives": the composition check is the one that actually holds the
property, because it runs against class objects with no comment to escape it.
A static approximation that is *weaker* than the runtime gate is a false green;
one that is *equal* is a fast failure. Only the second is worth having.

### 3. Cross-owner maintenance stays unsupported, and that is now a decision

There is no supported route for a job that must legitimately touch rows across
owners, and no maintenance-authority capability ships. Both messages say so. This
record makes it a position rather than an omission:

- The system actor is not an escalation and will not become one implicitly.
- The marker will not be extended to the composition half. A source comment cannot
  survive to the point where the property is checked, and a check that reads a
  comment is a check an app edits.
- The shape a supported route would take is named here so it is not reinvented:
  an explicit, audited **maintenance authority** — a capability that issues a
  scoped, time-bounded grant which the write chokepoint recognises, so that a
  cross-owner write is an event in the audit log rather than the absence of a
  check. That is a capability with its own record, its own tests and its own
  release. It is not this one.

Until it exists, the honest answer to "what may an app do for cross-owner
maintenance" is: nothing that ships, and the gap is the platform's rather than the
app's.

### 4. Built with the record, in one release

This record and its closure both land in **0.14.0**, which is this repository's
usual convention (an ADR is amended *by building it*) rather than an exception to
it. An earlier draft of this section deferred the code a release, on the grounds
that the change touches an authorization gate; that caution was misplaced once the
shape was clear, because the hole is one line wide and the fix is a closure over
data both halves already hold.

What does **not** ship here is the terp-spec side. Residuals 1 and 2 stay recorded
in `RESIDUALS.json` even though the framework now exceeds them, and that is
deliberate: a residual states what the conformance corpus does not *require*, so a
reference implementation is free to be stricter. Dropping them tightens the bar
for every implementation and belongs to a spec release, taken in the order the two
circularly-coupled CIs need (spec first, then framework, then re-run spec).

Residual 3 — a `ModuleSpec` that omits `services=` — is untouched and stays open.

## Consequences

- The dodge is closed and named, so a reader who finds the old advice quoted
  anywhere else can see what replaced it and why.
- Two of the three recorded residuals are now exceeded by the reference
  implementation. The third (`services=` omitted) is untouched and stays a
  residual.
- Apps whose jobs reach an unowned service across a declared edge now fail, at
  build and at boot. That is the point, and it is a breaking change for any app
  relying on the hole — announced as one in the 0.14.0 notes, with the legitimate
  split (two modules, no edge) still passing untouched.
- `# arch-allow-no-manual-ownership-checks` keeps exactly the meaning it has: the
  build gate only, never the composition gate.

## Alternatives considered and not taken

- **Narrow the composition check to match the build check.** The two would agree
  and CI would stop lying, at the cost of the only half that actually holds the
  property. A gate is not improved by lowering it to its own approximation.
- **Extend the marker to the composition half.** Rejected on the mechanism, not
  the policy: a comment does not exist at composition. Threading a
  build-time-discovered allowlist into the runtime would make the runtime gate
  readable from source, which is what makes the build gate escapable in the first
  place.
- **Delete the "different modules" advice and offer nothing.** The advice is
  correct whenever no edge is declared, which is most of the time. Removing a
  usable remedy because it has one hole, rather than closing the hole, would make
  the platform less usable and no safer.
- **Ship the maintenance-authority capability now.** The right long answer, and
  far too large to attach to a gate repair. Named in § 3 so the shape is on record.
