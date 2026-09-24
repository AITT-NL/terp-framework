# 0149 — A read behind a grant records that it happened

- **Status:** Accepted and implemented (framework half). The
  `permission_gated_reads_disclose` rule ships and is listed in
  `_AWAITING_SPEC_RELEASE` until its terp-spec catalog entry is published. Held by
  `tests/architecture/test_arch_harness.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0118](0118-the-trail-records-a-disclosure-and-a-read-may-write-that-one-row.md) (the seam this
  gives a reason to exist), [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md) (the
  two-repo order this follows), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (the budgeted escape hatch), [ADR 0084](0084-runtime-applicability-classification.md) (why
  the runtime half is a recorded decision rather than an omission)

---

## Context

The audit trail is emitted from the `BaseService` write chokepoint. That is what makes it
unbypassable — a module cannot persist without passing through it — and it is also what
makes it **mutation-only**. Nothing anywhere records a read.

So the trail answers *who changed what*, and never *who looked*. For a great deal of what
applications built on this platform hold, looking is the entire harm: a connection profile
with its host, port and credential references; a salary; a case file; a customer list. A
principal who can read those can enumerate them and leave nothing behind.

ADR 0118 supplied the missing half: `emit_disclosure`, which opens its own session (a read
has no unit of work to ride, and the request's session is doubly write-guarded during a
safe method), clears the read-only flag through `fresh_write_scope`, and emits **before**
the data is handed over — so a sink that raises fails the endpoint and nothing is
disclosed. The record is the precondition of the disclosure, not a report on it.

What ADR 0118 did not supply is any reason for a route to call it. **Nothing in the
platform does.** A grep for callers returns the definition and its tests. The `access`
guide topic already teaches the pattern, in as many words — and a documented pattern with
no enforcement is the shape this repository has a rule for.

## Decision

**`permission_gated_reads_disclose`: a safe-method route gated by a named permission must
call `emit_disclosure`.**

**Which reads.** Not all of them, and that restraint is the design rather than a
concession. A record per read of everything is noise that buries the one entry somebody
will eventually need — the `access` guide says exactly this about auto-emitting. The
signal is already in the source and was written by the author: a route carrying
`require_permission(...)` is one where somebody decided the module's role tier could not
express the decision. "Any editor may read here" was not good enough, so the route asks
for a named grant on top. That is this platform's own marker for *sensitive*, and it is
the one the rule reads. It needs no new flag on `Permission` or `Policy`.

**Safe methods only.** A write behind the same grant is already audited through the
chokepoint. Asking it to disclose as well would record the same event twice and blur what
a disclosure means.

**Both spellings of the marker count** — `dependencies=[Depends(require_permission(...))]`
and the requirement declared in the endpoint signature. A rule that read only the first
would be blind to precisely the form `route_permission_names` had to be fixed to notice at
runtime; the route's authority was reported as the tier alone, and a rule repeating that
mistake would exempt the routes most likely to be hand-wired.

**The escape hatch is real, not ceremonial.** A justified
`# arch-allow-permission-gated-reads-disclose: <reason>` marker, ratcheted by the
escape-hatch budget. The genuine case is a grant that gates an *action* rather than a
disclosure — a route that starts something and returns an acknowledgement reads no
protected data and has nothing to record.

## Why this is build-time only, on purpose

ADR 0084 requires every rule to record a `runtime.applicability` rather than leave the
question open, and the honest answer here is **deferred**, with a shape.

The invariant is observable at runtime: the guard knows the requirement it applied, and a
middleware could know whether a disclosure was emitted during the request. A fail-closed
control is even constructible — refuse the response when a permission-gated safe method
produced no disclosure — because at middleware level the response has not been sent.

It is not shipped here for one reason: **the guard cannot write the record the rule is
asking for.** It knows the principal, the module and the requirement; it does not know
*what was disclosed*. `emit_disclosure` takes a `target_type` and a `target_id`, and a
record that says "somebody read this endpoint" is a weaker artifact than one that says
"somebody read payroll export 41" — weak enough that emitting it automatically would
satisfy the rule while answering the wrong question. Only the endpoint knows what it
returned, which is the same reason the seam takes those arguments at all.

A response-time refusal remains available and would pair with this rule without changing
it. It is a separate decision, with its own cost: it makes every permission-gated read in
every existing application fail until it discloses, which is a migration rather than a
control.

## Consequences

**The two-repo order applies (ADR 0116).** The rule ships here with its name in
`_AWAITING_SPEC_RELEASE`; the terp-spec catalog entry, a spec release and the pin bump
follow. `test_release_versions` requires that set to be empty before a framework release
can be cut, so the window cannot be left open.

**No shipped code changes behaviour.** No capability in this repository has a
permission-gated read, so the rule finds nothing here today. It is aimed at consumers,
which is where the finding was found: a principal holding a read grant could enumerate
every production connection profile and leave no trace.

**An application adopting this will have work to do**, and that is the point. The rule
names the route, and the fix is two lines the `access` guide already documents.
