# 0120 — The self-labelling controls carry their own field envelope

- **Status:** Accepted
- **Date:** 2026-09-06
- **Relates:** [ADR 0096](0096-typed-seams-cover-the-common-case.md) §4 (the last react-core
  component request, refused because its own cited evidence contradicted it — the discipline
  that produces is applied here, and points the other way),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced — the reason this is props on the three controls rather than a second envelope
  component a caller could pick wrongly)

---

## Context

`Field` is how this platform authors an accessible form control. It wraps the control in a
`<label>` — so the label is the control's accessible name with no id wiring — and renders an
optional hint and a field-level error, each given an id, pointed at by `aria-describedby`,
with the error also carrying `role="alert"` and setting `aria-invalid`.

Three controls cannot use it. `Switch`, `Checkbox` and `RadioGroup` each label *themselves*:
the first two render their own `<label>` around their input, and the group renders a
`<fieldset>` with a `<legend>`. Nesting any of them in `Field` produces a `<label>` inside a
`<label>`, which HTML forbids and browsers resolve by associating the control with the outer
one — so the field's label text is lost and its `aria-describedby` lands on a label rather
than on the input.

The consequence was not that these three had a slightly worse API. It was that **they had no
hint or error affordance at all**, and the platform's own guide said so in as many words,
recommending that a hint be placed beside them as loose `<Text>` — which is invisible to a
screen reader, because text next to a control is not announced unless something points at it
— and that an error go into a form-level summary. That guidance was honest about being a
workaround, and it is the evidence this entry needed: the platform documented a degraded
path rather than a supported one.

**The bar this has to clear, and what it actually is.** The last react-core component
request — a general `Dialog` — was refused in ADR 0096 §4, and not for want of a consumer:
it was refused because *the reporting application's own cited evidence contradicted the
request*, saying the alternative shape had turned out better. The discipline that produces
is to read the evidence before designing the fix, rather than to treat a request as its own
justification.

Applied here, the evidence points the other way, and it is the platform's own. The guide
documents the gap, recommends a workaround, and names the case the workaround cannot cover:
a boolean cannot hold a value its type refuses, so a switch has little to be wrong about —
but **a required `RadioGroup` can be left unset**, and that rejection had nowhere to go
except a form-level `ErrorState` that never names which question was unanswered. Nothing
here rests on a consumer's report. A platform that documents a degraded path, in its own
guide, because the supported one does not exist, has made the argument for building it.

## Decision

`hint` and `error` become props on `Switch`, `Checkbox` and `RadioGroup`, with the wiring
shared with `Field` through one internal `useControlMessages` hook.

**Props on the three, not a second envelope component.** A `ControlField` sibling to `Field`
would have been the symmetric shape, and it would have created a choice a caller can get
wrong — picking `Field` for a checkbox produces nested labels, silently, with no error
anywhere and a control that still looks fine. Making the affordance a prop on the control
that needs it removes the wrong option instead of documenting it. It also means the three
read like every other control: `label`, `hint`, `error`.

**One implementation, shared with `Field`.** The point of giving these three the envelope
separately is that "separately" must not become "differently". The ids, the
`aria-describedby` composition, the `aria-invalid`, and the error's `role="alert"` now come
from a single hook that `Field` also uses, so the four cannot drift apart in behaviour while
looking alike.

**A caller's own `aria-describedby` is added to, never replaced.** A control already pointing
at a description keeps pointing at it; substituting the field's ids would silently drop
something the caller added deliberately, and assistive technology would simply stop reading
it with nothing anywhere reporting a problem.

**The wrapper is unconditional, and this is the non-obvious part.** Rendering the wrapping
`<div>` only when there is a hint or an error would change the element type at that position
the moment an error arrives, so React unmounts the label and mounts a fresh input — and an
**uncontrolled control loses its state at exactly the moment the form tells the user
something is wrong**. This is not a theoretical concern: the conditional shape was written,
mutated back in, and the test that names the behaviour fails on it. The wrapper's
`justify-items: start` is what keeps the unconditional version from costing anything, holding
the control's own `<label>` at its intrinsic width so its click target does not grow to fill
the column.

**For `RadioGroup`, the description and the invalid state belong to the group.** The thing
left unanswered is the question, not any one radio. Marking each option would repeat the
message on every arrow-key move through the group; marking the `<fieldset>` states it once,
where the legend already is.

## Consequences

- A required choice can now be rejected next to the question it is about, which is the case
  the guide had recorded as having no answer.
- The guide's "honest limitation" paragraph was false the moment this shipped, and is
  rewritten in the same commit — it is the passage that sent authors to the inaccessible
  workaround, so leaving it would have been worse than never having written it.
- Existing call sites are unchanged: both props are optional, and a control with neither
  renders the same label and input it always did, now inside a wrapper that adds no spacing
  of its own.
- The wrapper is one extra element in the DOM of every `Switch` and `Checkbox`. That is the
  price of the remount guarantee above, and it is worth it.
- `data-terp="control-field"` joins the marker ledger, so the stylesheet and the rendered
  markup stay in agreement.
- A caller can still pass one of these three to `Field`, and nothing stops them. The invalid
  nesting is not detectable in the type system, and this platform does not warn at runtime.
  A lint rule on the frontend surface is where that check belongs; it is not written here.
  The trigger: the first time someone does it.

## Alternatives considered and not taken

**A `ControlField` component beside `Field`.** Symmetric, and it puts a wrong answer within
reach: `Field` around a checkbox is invalid HTML that renders without complaint. Props on the
control remove the choice rather than documenting it.

**Make `Field` detect a self-labelling child and render a `<div>` instead of a `<label>`.**
One entry point, which is appealing. But `Field`'s `label` prop is required and would then
compete with the control's own — two labels, one of them redundant, with nothing to say which
wins. The nesting problem would be gone and a naming problem would replace it.

**Leave it, and keep the guide's workaround.** The position until now. It is defensible for
the booleans and indefensible for the group: a required choice that can be left unset needs
somewhere to say so, and "put it in the form-level error" loses which question was
unanswered — the one piece of information the message exists to carry.

**Warn in development when `Field` wraps a self-labelling control.** The most direct guard,
and it is not available: this package does not log warnings, deliberately, so a runtime
console message is not a mechanism here. A lint rule is the mechanism, and is left as a
follow-up rather than smuggled in as a console call.
