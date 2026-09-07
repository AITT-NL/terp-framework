# 0121 — Marketing websites are not a Terp application kind

- **Status:** Accepted
- **Date:** 2026-09-07
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (the
  ideology whose audience justification this domain inverts),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (the
  removes-a-capability-or-removes-silence test, applied here and failed),
  [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (the name-a-consumer test, and
  the reason a refusal is written down rather than remembered),
  [ADR 0005](0005-security-middleware-and-structured-logging.md) (the two-layer enforcement
  this domain cannot satisfy), [ADR 0084](0084-runtime-applicability-classification.md) (the
  vocabulary in which every rule of a site product would be classified),
  [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (low-code refused as a
  target), [ADR 0093](0093-semantic-token-layer-and-named-themes.md) and
  [ADR 0094](0094-attribute-keyed-styling.md) (the token layer, which is the one artefact
  that does travel).

---

## Context

A batch of marketing websites was to be delivered, and two proposals followed from it: widen
this framework so such sites can be built on it, or admit a second **kind** of Terp
application — a "site" kind — alongside the application kind, with its own layout contract,
its own rule catalog and eventually its own workbench archetype.

Both are refused. This ADR is what surveying them produced, and it is written down for the
reason ADR 0099 gives for its own thirteen refusals: a refusal that lives only in someone's
head is re-proposed every few months, and each re-proposal costs the same survey again.

The second proposal is the more serious of the two, and it deserves to be refused on its
merits rather than confused with the first. Widening the framework would weaken rules that
other consumers depend on; a separate *kind* would not. It fails for different reasons.

## Decision

### 1. The domain has no authority seam, so two-layer enforcement collapses

Every control this framework is organised around answers one question: *an untrusted actor
has made a request; what may it do to persistent state?* That is what `ModuleSpec` and
`Policy` exist for, and what the fail-closed runtime controls, the role and scope model, the
ownership checks, the audit emission and the idempotency keys are all in service of.

A static marketing site has no actors, no persistent state, no requests and no authority
decisions. Its whole threat model is: do not accept spam through a form, do not ship a
hostile third-party script, do not break.

The consequence is structural rather than a matter of degree. This platform's second
non-negotiable is that a runtime-observable rule is a fail-closed runtime control **and** a
build-time test — the test catches the omission, the control protects production. For a site
kind, every rule would classify as `not-applicable` in ADR 0084's runtime vocabulary, because
there is no runtime to observe. The kind would inherit the build-time half of the model and
none of the half that distinguishes this framework from a linter.

What would actually transfer is a token system, a lint rule set, a scaffolder and the habit
of writing decisions down. Those are worth having and **none of them is this framework.** A
product that shares CSS custom properties with Terp is not a kind of Terp application, and
calling it one would make the phrase mean nothing.

### 2. Enforcing one pattern here removes the capability that carries the value

For a business application the enforced pattern *is* the domain. Record lists, record
detail, an edit form, a permission check, a trail — a set of such applications is
overwhelmingly the same shape, and visual uniformity is a feature, because the people using
them learn one shell. The design is not the product; it is chrome around data.

For a marketing site the variable part is the product. What a client is buying is
differentiation, so enforcement lands precisely on the axis with commercial value.

Apply ADR 0111's test literally — *does this constraint remove a capability, or does it
remove silence?* It removes a capability. Its escape clause requires "a safety argument the
intended audience could not have made for themselves", and there is no such argument
available: nobody is breached by a page layout. And ADR 0099's test asks for a consumer in
this framework for the components such a kind would need. There is none for a hero band or a
logo wall, and there never will be, because every consumer would live in the other product.

### 3. The audience justification inverts

ADR 0103 justifies the strictness by the audience: someone who cannot evaluate a security
trade-off must not be offered one. That is correct, and it is why this framework enforces
rather than advises.

The decisions a marketing site needs are aesthetic and editorial. There, the person deciding
is the expert and the framework is not. Enforcing against them is enforcing against
competence, which is the inverse of the justification — the ideology's own logic says to
enforce where the user cannot judge, and not where they can.

### 4. Two artefacts travel, and they are vendored rather than depended on

The design tokens (ADR 0093) and the measured contrast gate that holds each theme to WCAG
are genuinely reusable for brand work at any scale, and they carry no application coupling.
They are **copied into** a site's own tree rather than depended on as a package, because the
platform releases in lockstep with an application product that a website has no stake in.

Nothing else travels. In particular the frontend primitives are not extracted for this
purpose: their styling is attribute-keyed with `style` and `className` refused (ADR 0094),
which is correct for an application surface and wrong for the layer that would have needed
them.

### 5. What is not refused: an app as an audited content backend

Where an organisation must control its own published copy under review, an **ordinary Terp
application** is a good content backend — editor-versus-approver on the existing role model,
a trail on every change, media through the files capability, and copy through the checked
localization contract. That is the business-application shape this framework is for,
consumed by a site rather than replacing it, and it requires no change here.

## Consequences

- Website work is delivered outside the platform with ordinary static tooling. No change is
  made to this framework, its capabilities, its rule catalog or its templates.
- The `contract` vocabulary in the frontend layout manifest keeps its single value. A `site`
  contract is not added, and no page archetype is added for a public marketing page.
- The frontend primitives are not split into their own package. The consumer that justified
  the split was the site product, which will not exist.
- **The condition under which this should be revisited**, stated so the reversal is evidence
  and not argument: if a batch of such sites turns out to be structurally identical, such
  that only the palette, the logo and the copy differ, then the pattern would in fact be the
  domain and §2 weakens. The test is a real set of briefs, not a hypothetical one. If instead
  even a few need a layout nobody anticipated, the escape hatch becomes the normal path — and
  an escape hatch used on every page is not an escape hatch, it is the API, arrived at by
  erosion instead of by decision.
