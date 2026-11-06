# `backend/no_manual_actor_stamping`

**Modules never write or gate on the framework-managed actor-stamp columns**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_actor_stamping.json`.

## Why this rule exists

Who created and last modified a row is provenance, applied centrally: the audited write chokepoint fills created_by_id (on insert) and modified_by_id (on every write) from the request actor. Two shapes are refused, for two different reasons. Assigning or deleting those columns forges or clobbers the trail - the actor must come from the authenticated request, never from caller-supplied data, and a hand-written stamp is indistinguishable afterwards from one the platform wrote. Comparing a stamp against a principal is object-level authorization written inline, which belongs to the ownership seam, where it is applied at the write chokepoint rather than wherever someone remembered it. Reading a stamp is NOT refused. A read cannot forge a trail, and the ordinary uses are legitimate: exposing provenance on a read DTO, rendering it, logging it, or asking whether a row has been stamped at all - a comparison against a literal is a presence test, not a decision. A rule justified by forgery that also refused a plain read would be refusing the thing the trail exists to make visible. The two sibling rules over the managed scope and ownership columns stay broader on purpose, and the asymmetry is the decision rather than an inconsistency: for those a read is the first half of a hand-rolled gate or scope filter and no static check can tell it from a display read, while an actor stamp has no corresponding harm on the read side. There is a fourth shape, and it is neither of the refused two: uniqueness keyed on the actor - may a SECOND row by this principal exist. The ownership seam does not answer it, because that seam decides whether an actor may act on a row and never whether another row may be created, so an author who reaches for the query form and is refused can reasonably conclude the requirement is unavailable. It is not. The reference names the shape that expresses it, and says why the query form stays refused.

## How Terp realises this

ActorStampedMixin columns are stamped by BaseService._save (ADR 0012). An assignment, an augmented assignment or a `del` of created_by_id / modified_by_id is refused, and so is a comparison against anything but a literal (`row.created_by_id == actor.id`, and the same expression inside a `where(...)`). `row.created_by_id is None` and a load that only reads the value are not; a read DTO exposing the column as an annotation was never attribute access at all. Gate on ownership with OwnedMixin instead of on the stamp. Per-actor uniqueness - one decision per reviewer per record - is expressed as a table constraint, `UniqueConstraint("record_id", "created_by_id")` in `__table_args__`, and is deliberately not policed: the column is named as a string, the database enforces it, and it is race-free where a check-then-insert probe is not, because two concurrent requests both pass the probe and both insert. The equivalent query stays refused because no static check can tell a uniqueness probe from an inline authorization filter - they are the same expression - so admitting it would reopen the shape this rule exists to close. The refusal therefore pushes an author toward the stronger implementation, which is the part that was never written down.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-actor-stamping: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a stamp written through the attribute API (`setattr(row, "created_by_id", ...)`) is not required to be seen as an assignment
- a comparison expressed as a method call on the column (`.in_(...)`, `.is_(...)`) rather than as an operator is not required to be seen as a comparison

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_manual_actor_stamping`
- `runtime`: `terp.core` — `BaseService`
