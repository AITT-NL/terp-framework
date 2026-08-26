# 0103 — The ideology: one pattern, enforced, escapable only by proof

- **Status:** Accepted
- **Date:** 2026-08-26
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the Tier A/B/C
  policy and the quadruple — the *mechanism* this ADR states the *purpose* of),
  [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (Target A / Target B and the
  low-code trap), [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the name-a-consumer
  test, generalised here), and `terp-studio` ADR 0004 (the plain-language principle that follows
  from the audience clause).

---

## Context

The framework's governing ideology has been applied consistently for a long time and written
down in three places, none of which states it as such. ADR 0006 gives the mechanism (tiers, and
the quadruple every control must ship as). ADR 0009 gives the authoring boundary (drift is
pushed to zero; "no unexpected code in a module at all" is the low-code trap and is refused).
ADR 0099 gives a decision test for one category (a component that cannot name a consumer is
declined).

What no document states is the ideology itself, and one clause of it has never been recorded at
all: **flexibility in usage patterns is refused**, with a closed list of reasons that can justify
a deviation. That omission has a cost. An unwritten principle is re-argued from scratch every
time it is challenged, and the answer drifts with whoever is answering — which is exactly the
failure ADR 0099 identified for refused components ("a refusal that lives only in someone's head
gets re-proposed every few months").

This ADR is therefore a *statement*, not a change. Nothing in the platform behaves differently
because it exists. It is written so that the next proposal can be measured against it, and so
that a disagreement is a disagreement with a document rather than with a person.

## Decision

### 1. The ideology

**Enforce a pattern; never limit a capability.** The framework is strict about *how* something is
done and indifferent to *what* is achieved. Enforcement that removes a second way of doing an
already-supported thing is correct. Enforcement that removes a capability is a defect in the
enforcement, not an acceptable cost.

**The default is the most secure, most enforced standard — on both sides of the stack.** Security
is the default, not a configuration. A control implemented only in the backend is half-built; the
frontend is held to the same posture, and where it is not, that is a gap to close rather than a
boundary to respect.

**Escape is always possible and never quiet.** Nothing is absolutely forbidden, because a
framework that forbids outright stops being usable for the case its authors did not imagine.
Nothing is quietly permitted either. The escape route is an explicit declaration, greppable,
justified in the same change, and ratcheted by a checked-in budget.

**The design centre is a person who cannot evaluate a security trade-off.** The initial audience
has little or no software-development knowledge. This is not an edge case to accommodate — it is
the centre. Flexibility for advanced use is retained, deliberately, but it is the secondary
concern and loses when the two conflict.

**Agentic coding is the medium.** The code is written by an agent on that person's behalf. Two
consequences follow, and they are what make the rest of this ADR load-bearing rather than
stylistic:

- **A rule that exists only as prose is not a control.** Nothing stops the next agent from
  writing around it. This is the ideological root of ADR 0006's quadruple: every control ships a
  fail-closed runtime half *and* a build-time half, because an instruction has neither.
- **The failure message is the primary interface.** An agent reads the error, not the
  documentation. A control whose violation does not name its own remedy is, for the actual user
  of this framework, an unusable control — which is why every rule carries a fix recipe and the
  completeness of that mapping is itself gated.

**Flexibility that exists only to serve the rare case is refused.** Two refusals in particular:
the platform does not become escapable everywhere in order to serve the last few per cent of
applications, and **usage patterns admit no flexibility at all**. The framework defines the
pattern. A preference for a different style is not a reason.

### 2. The deviation test

A deviation from a defined usage pattern is admissible for exactly three reasons: **performance**,
**security**, or **a feature that genuinely cannot be implemented within the restriction**.

Stated only that far, the third reason swallows the rule. "It cannot be done within the pattern"
is always plausible, and an agent asked for something unsupported will reach for whichever
justification fits — so the clause has to demand evidence rather than a claim:

1. **Name the restriction.** Which specific rule, control or seam blocks the requirement. Not
   "the framework does not allow this" but the rule that says so.
2. **Show the attempt.** What was tried inside the sanctioned pattern, and how it failed. A
   deviation is admissible after the sanctioned route has been shown not to work, not instead of
   trying it.
3. **Route it through the guide.** `terp guide <rule>` is where this is adjudicated. Its existing
   contract already says the right thing — when no sanctioned construct exists, stop and report
   the exact human approval or platform capability required, rather than implementing a forbidden
   substitute. A deviation request that has not reached that point is premature.
4. **A human decides.** Taking an escape hatch is not an autonomous agent decision. The marker,
   the budget increase, and the recorded approval are the mechanism, and they exist precisely
   because the design-centre user cannot evaluate the trade-off and the agent must not pretend to
   on their behalf.

The burden of proof sits on the side of flexibility. Always. "An app might want it" is not a
reason; a second way to do a supported thing is a cost with no benefit.

### 3. What this ADR does not license

It is not a mandate to add enforcement. A rule with no failure mode it can actually observe is
ceremony, and ceremony is how a strict framework becomes one people route around wholesale. The
quadruple's four parts are the price of admission for a control, and a candidate that cannot pay
it is a product decision that stays out of `terp.core` — ADR 0006 already says so, and this ADR
does not weaken it.

Nor does it license enforcement whose failure the design-centre user cannot act on. A fail-closed
control with an inscrutable message is, for this audience, a control that makes the product
unusable — and unusable gates get disabled in bulk, which costs more security than the control
ever bought. "Maximum security" means the maximum that still yields a diagnosable, remediable
failure.

## Consequences

- **The frontend is measurably behind the posture this ADR states**, and is now recorded as a gap
  rather than a boundary. At the time of writing the Standard carries substantially fewer frontend
  rules than backend ones, only one of them has a fail-closed runtime half, and none names a fix
  recipe — so on the half of the stack this ADR holds to the same standard, an agent has the most
  room to drift and the least machine-readable feedback to correct itself. Reproduce the
  comparison by grouping `terp-spec`'s catalog entries by surface and counting `layer` and
  `runtime.applicability`. Closing it is its own sequenced work, not a side effect of this ADR.
- **ADR 0009's emphasis is narrowed.** It frames the audience as non-technical owners *and* the
  ordinary majority of apps, with the remainder "configuring non-default behaviour". That remains
  true, but where the two pull apart, the design centre wins: this ADR makes the advanced case
  explicitly secondary, which ADR 0009 does not say.
- **A refusal now has somewhere to be recorded.** A rejected request for pattern flexibility cites
  this ADR and, where the argument is substantive, earns an entry in the refusal register ADR 0099
  established for components.
- **This ADR is testable in one direction only.** It states intent, so nothing enforces it; it
  earns its keep by being the thing a proposal is measured against. If it ever conflicts with a
  merged ADR that changes behaviour, the behavioural ADR wins and this one is amended.
