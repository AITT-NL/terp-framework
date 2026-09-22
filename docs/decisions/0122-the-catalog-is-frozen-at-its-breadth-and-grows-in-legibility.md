# 0122 — The catalog is frozen at its breadth, and grows in legibility instead

- **Status:** Accepted
- **Date:** 2026-09-07
- **Relates:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) (the catalog
  and corpus this governs the growth of),
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md) and
  [ADR 0083](0083-findings-envelope-and-evaluated-rule-inventory.md) (the findings surfaces
  the redirected effort lands on),
  [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the name-a-consumer test, here
  applied to rules rather than components),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (the audience whose
  perception this ADR takes seriously),
  [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md) (a rule may precede
  its entry — this ADR does not change that, it changes what earns a rule at all).

---

## Context

The standard has reached a breadth where the next rule is, commercially, invisible.

The audience the platform now targets cannot evaluate a security trade-off — that is the
premise ADR 0103 builds the whole enforcement posture on, and it is why enforcing rather than
advising is right. But the same premise has a consequence that has not been written down: such
a buyer cannot perceive the enforcement either. A gate becomes visible only when something
bad does not happen, and a thing that does not happen is unattributable. Nobody thanks a rule.

So the marginal rule and the marginal *explained refusal* have very different values, and the
catalog has been receiving the effort. Each additional rule adds real protection and no
perceptible product; making an existing refusal explainable to the person who owns the
application adds no protection and a great deal of perceptible product. Both are cheap to
build. Only one is currently being built.

The risk of leaving this unstated is not that someone adds a bad rule. It is that "the
category looks incomplete" keeps functioning as a sufficient reason, indefinitely, because
a catalog can always be more complete.

## Decision

### 1. Breadth is frozen. Correctness is not

No rule is added because a family looks unfinished. Everything that keeps the existing set
honest continues unchanged: a wrong rule is fixed, a rule whose enforcement has drifted from
its entry is repaired, an entry whose `runtime.applicability` is misclassified is corrected,
and corpus coverage continues to advance — `corpus/PENDING.json` is already a ratchet that
only shrinks, and this ADR does not slow it.

### 2. A new rule needs a consumer outside the catalog

ADR 0099's test, applied to rules: a rule that cannot name a failure it would have caught in
a real application is declined. "The category is incomplete" is not a consumer, in the same
way "an app might want it" was not one for a component.

This is deliberately a high bar and it is meant to be argued against on evidence — an observed
incident, a review finding, a class of mistake an agent actually made. Any of those clears it
immediately.

### 3. The redirected effort goes to explaining refusals, not to finding more of them

The work this frees is the owner-facing half of a finding: what the refusal *means* to the
person who owns the application, in their language, rather than what rule it violated. A
refusal that reads "this would have let any signed-in user read other customers' records" is
the product demonstrating a value the buyer otherwise never observes; the same refusal
reported as a rule id is not.

Where that lands as a field on a catalog entry, **the field arrives with its reader and not
before** — the workbench surface that renders it — because a published field nothing consumes
is a maintenance obligation with no benefit.

### 4. The standard's claim is untouched

The assurance-lane vocabulary and each lane's requirement level are normative and stay exactly
as they are. This ADR governs what earns a *new* rule; it changes nothing about what a
conformant checker must emit, what an assurance profile claims, or what a certified toolchain
was certified against.

## Consequences

- A proposal for a new rule is answered with the evidence test in §2, and the answer is
  recorded rather than debated again.
- The corpus ratchet, the findings envelope and the certification flow are unaffected.
- The spec's own version continues to move for corrections and for corpus growth, so a frozen
  breadth does not mean a frozen `VERSION`.
- **This should be revisited** if the evidence test starts refusing rules that later turn out
  to have been needed — the signal being a real failure in a real application that an
  already-proposed-and-declined rule would have caught. That is a reason to lower the bar, and
  it is the only one this ADR accepts.
