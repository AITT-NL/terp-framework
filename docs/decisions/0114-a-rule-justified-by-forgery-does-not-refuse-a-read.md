# 0114 — A rule justified by forgery does not refuse a read

- **Status:** Accepted
- **Date:** 2026-09-05
- **Relates:** [ADR 0012](0012-actor-stamping-trait.md) (the actor stamp itself, and the
  write chokepoint that fills it),
  [ADR 0029](0029-object-level-ownership-authorization.md) (the ownership seam an inline gate on a
  stamp belongs to),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced, escapable by proof — a rule whose refusal is wider than its stated reason
  spends that budget on nothing),
  [ADR 0084](0084-runtime-applicability-classification.md) (a rule's scope is
  recorded data, not folklore)

---

## Context

`no_manual_actor_stamping` refuses module code that touches `created_by_id` or
`modified_by_id`. Its stated reason is forgery: the stamp must come from the authenticated
request, so a module that writes one is forging or clobbering the trail.

Its prose then said, in the docstring and in the catalog entry both:

> only attribute access (set / compare) is policed

That sentence contradicts itself. *Attribute access* is the broad thing; *set or compare* is
the narrow one. The detector did the broad thing — every `ast.Attribute` whose name matched —
so `if row.created_by_id is None` was refused by a rule justified by forgery, and so was
returning the value in a dictionary, and so was putting it in a log line.

**The cost was not the false positive.** It was what a careful reader concluded from it. Told
that a rule forbids reading provenance, and reading the sentence that says only set and
compare are policed, the honest conclusion is that the rule does not mean what it says and
that the design being attempted is refused. That reader then designs around a wall that was
never there. A refusal wider than its own justification does not merely cost a suppression
comment; it costs the credibility of every other refusal in the same file.

The escape hatch existed and worked — that half was corrected separately, in the budget's
key-mismatch message. What is left is the question the hatch cannot answer: **what is this
rule actually for?**

## Decision

**The rule follows its harm. Writing a stamp is refused, gating on a stamp is refused,
reading a stamp is not.**

Three shapes, and each is refused or allowed for a reason that can be stated in one line:

**Assigning or deleting is forgery.** `row.created_by_id = actor.id`, its augmented form, and
`del row.created_by_id` all replace a value the platform owns. Afterwards a hand-written stamp
is indistinguishable from one the write chokepoint wrote, which is exactly the property a
provenance trail must not have.

**Comparing against a principal is object-level authorization, written inline.**
`note.created_by_id == actor.id` is a per-row gate. It is not forgery, but it is the
hand-rolled version of a decision the ownership seam applies at the write chokepoint (ADR
0029), where forgetting it is not possible. The same expression inside a `where(...)` is the
same decision, so it is refused on the same footing.

**Reading is neither, and the ordinary uses are the point of keeping the trail.** Exposing
provenance on a read DTO, rendering "created by", writing it to a log, or asking whether a row
has been stamped at all. A read cannot forge anything, and it cannot decide anything either.

The boundary between the second and third shapes is what a comparison is *against*. A
comparison with a literal — `is None`, `== None` — names no principal, so it decides nothing;
it is a presence test wearing a comparison's syntax. A comparison with anything else names
something to compare a principal to, and that is a decision. That line is exactly expressible
in a detector and exactly explainable in a sentence, which is the bar a rule's scope has to
clear.

### The two sibling rules keep the broad reading, and the asymmetry is the decision

`no_manual_scope_filtering` and `no_manual_ownership_checks` share this rule's code shape and
refuse plain reads too. They stay that way, and this ADR is the record of why, so the next
reader does not file the same finding against them.

For `deleted_at`, `tenant_id` and `owner_id`, **a read is the first half of the harm.**
`if row.deleted_at is None` inside module code *is* the hand-rolled scope predicate the
central `base_query` exists to replace; a load of `owner_id` is the first half of a per-row
gate that leaks the day someone forgets it. No static check can tell that read from a display
read, and the direction to be wrong in is different for each rule: for a gate you must not
under-refuse, for a provenance trail you must not over-refuse.

For an actor stamp there is no such second half. Everything a read of `created_by_id` can do
is either display — which is sanctioned — or a comparison, which this rule still refuses on
its own terms. That is why one rule narrows and two do not, and both sibling catalog entries
now carry the sentence rather than leaving it to be inferred from a detector.

## Consequences

**A contract change in the permissive direction.** An application that failed on a stamp read
passes now; nothing that passed starts failing. The two existing corpus violations were both
assignments, so nothing that failed for the right reason changes verdict. Three corpus cases
contract the new boundary in both directions — a violation for the inline gate, compliant
cases for the plain read and for the presence test — because a narrowing that is not
contracted is indistinguishable from a detector that got weaker by accident.

**Two residuals are recorded rather than claimed.** A stamp written through `setattr` is not
required to be seen as an assignment, and a comparison expressed as a method call on the
column (`.in_`, `.is_`) is not required to be seen as a comparison. Both are the ordinary
limits of an AST-shaped check, and both belong in data (`corpus/RESIDUALS.json`) rather than
in a reader's memory.

**The prose is now the specification.** The sentence that started this said one thing while
the code did another, and the code won by default. Every rule in this family now states which
shapes it refuses and, where it refuses more than its headline reason implies, why.

## Alternatives considered and not taken

**Leave the behaviour and rewrite the prose to say "any access is refused".** Honest, and
cheaper. It was rejected because it defends the wrong half: the sentence was wrong *because*
the behaviour was wider than the justification, and rewriting the sentence would have made
the rule permanently harder to defend the next time someone asks why a log line is a
conformance failure. The sibling rules take exactly this option — but only because for them
the wide behaviour is the correct one.

**Narrow to assignments only.** Simpler to implement and simpler to explain, and it opens a
real hole: a module could gate a write on `created_by_id` and no rule anywhere would see it,
because `no_manual_ownership_checks` watches `owner_id` and nothing else. A rule that refuses
forgery while permitting the inline gate right beside it is not a smaller rule, it is a
differently-shaped one with a gap in it.

**Treat every comparison as a decision, including `is None`.** This is what the detector did,
and it is the specific false positive that produced the finding. A presence test names no
principal. Refusing it costs a suppression comment on a line that is doing nothing wrong, and
teaches that the rule's refusals are not to be read literally — which is how a wall that was
never there gets designed around.
