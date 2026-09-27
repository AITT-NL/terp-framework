# 0157 — A descriptor is written where it is used

- **Status:** Accepted and implemented in `@terpjs/eslint-boundaries`
  (`terp/locale-catalogs-complete`). The matching change to the Terp Standard's catalog
  entry and corpus is in terp-spec; this repository adopts it with the next spec release.
  Held by `packages/frontend/eslint-boundaries/src/i18n.test.js`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0105](0105-localization-is-a-checked-contract.md) (the checked
  localization contract this narrows a gap in),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (the
  governed opt-out)

---

## Context

`terp/locale-catalogs-complete` inventories every UiText descriptor an app writes and
refuses one whose id is missing from a target locale in `frontend/i18n.json`. It reads
descriptors where they are written: an object literal with a literal `id` and `message`, or
a `<Trans>` element.

A helper defeats that. With `const msg = (id, message) => ({ id, message })`, the screen
writes `title={msg("widgets.title", "Widgets")}`. The object literal the rule inspects is
inside the helper and holds no literals, and the copy sits in a call's arguments, which the
rule never reads. So a target locale could be missing the entry and the gate stayed green.
It was reported from building an app on Terp: messages built by a helper function passed the
gate with a missing English entry.

This was not an oversight. The rule was written to leave an object whose `id` and
`message` are both dynamic alone, because the same shape is a common business-data record
(a notification with an `id` and a `message`). A test pinned exactly the positional form,
`(id, message) => ({ id, message })`, as "not a descriptor". The runtime `LocaleProvider`,
which refuses a missing target entry when the screen renders, was named as the backstop for
dynamic ids. That backstop fires only on a screen somebody renders, so it is not a gate.

## Decision

**A UiText descriptor is written where it is used. A function that builds one from its own
parameters is refused.**

- **What is refused:** an object with `id` and `message` whose values are *both* plain
  parameters of the function that encloses it. That is the positional factory, whatever
  its spelling: an arrow or declared function, typed or defaulted parameters, shorthand or
  explicit properties.
- **Reported under** `frontend/locale-catalogs-complete`, because the defect is copy the
  catalog inventory cannot see.
- **What the message says:** write the descriptor literally (`{ id: "…", message: "…" }` or
  `<Trans>`), and if the object is business data rather than copy, build it from the record.

**What is not refused, deliberately:**

- A record built from the record, such as `(record) => ({ id: record.id, message:
  record.text })`, or from a destructured object. Its values are not the caller's literals
  under another name.
- A key into data: `ids.map((id) => ({ id, message: labels[id] }))`, where only one value is
  a parameter.
- A helper that takes one descriptor object. Its call site still holds a literal descriptor,
  which the rule inventories as it always has.

This reverses the earlier allowance for exactly one shape, and it is the ideology's test
applied: the factory is a second way of writing a descriptor that removes a check, and the
business record it was protecting has an equivalent spelling that the rule still accepts.
The burden sits with the flexibility, and here the flexibility bought nothing the stricter
form cannot express.

The same change removes a false positive from `terp/no-untranslated-ui`. DataView's own
string keys (`columns`, `loading`, `pageOf`, …) were in the list of JSX attributes treated
as copy, so `<Grid columns="auto">` was reported as untranslated text, and an app could get
past it only with an escape marker. Those names are text only as keys of a DataView `strings` object, which the property
check still covers. As JSX attributes they belong to props that are not text, so they leave
the attribute list. `searchPlaceholder` and `actions` are real text props elsewhere and stay.

## Consequences

- An app with a positional descriptor factory fails lint on upgrade, with a message naming
  both ways out. It can also take the governed marker
  (`// terp-allow-locale-catalogs-complete: <reason>`) and have it counted in its budget.
- The static rule still does not see every dynamic id. A key assembled at runtime,
  `` { id: `status.${key}`, message: … } ``, is reported as a malformed descriptor where one
  half is static, and passes where both are dynamic, leaving the runtime check as the answer.
  That limit is unchanged and is not claimed to be closed.
- The spec entry gains the sentence and the corpus cases (a factory violation, the record
  shapes as compliant, and `columns="auto"` as compliant under `no-untranslated-ui`). The
  two repositories' CIs are coupled: the spec's certify job fails until this lands on
  framework `main`, and this repository's corpus test sees the new cases only after the
  spec release is adopted.
