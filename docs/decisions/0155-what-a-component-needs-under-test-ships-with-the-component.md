# 0155 — What a component needs under test ships with the component

- **Status:** Accepted and implemented. `@terpjs/react-core/testing` exports
  `installDialogPolyfill()`; react-core's own `vitest.setup.ts` and the template's
  `frontend/vitest.setup.ts` both call it. Held by
  `packages/frontend/react-core/src/testing.test.tsx` and by the `template-acceptance` CI
  step that runs a `ConfirmDialog` probe through a generated app's own `npm test`.
- **Date:** 2026-09-27
- **Relates:** [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (the
  boundary that refuses a raw `<dialog>` and deep imports),
  [ADR 0100](0100-the-layout-declaration-is-one-document.md) (the package's first declared
  subpath, `./layout.manifest.json`),
  [ADR 0119](0119-a-module-owes-tests-and-the-standard-recognises-two-places-to-keep-them.md)
  (a module owes tests, which makes the test seam part of the product),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced)

---

## Context

`ConfirmDialog` is the one dialog an app may render: the boundary lint refuses a raw
`<dialog>` and names it as the replacement. It is built on the native element and calls
`showModal()` and `close()`, so the platform supplies the focus trap, the top layer and
Escape.

jsdom implements the element and its `open` attribute but neither method. react-core's own
`vitest.setup.ts` carried a polyfill for them; the setup file a generated app ships did not.
So the first unit test an app wrote around a destructive action — the case the framework
tells it to guard with this component — threw `showModal is not a function` from inside
react-core, and the only remedy available to its author was to copy a block of platform code
out of a package they had no reason to have read.

The polyfill that existed was also thinner than the component it served. It toggled `open`
and nothing else, so pressing Escape did nothing at all. `ConfirmDialog` handles Escape in its
`cancel` listener — it cancels the event and asks its owner to close, or, while `isPending`,
cancels it and does nothing — and react-core's own tests reached that listener only by
dispatching `cancel` by hand. An app test that pressed Escape would have seen nothing happen,
and a test of the pending guard would have passed whether or not the guard worked.

## Decision

**react-core publishes the polyfill, and every setup file that needs it calls the published
copy.** `installDialogPolyfill()` lives in `src/testing.ts`, exported at the
`@terpjs/react-core/testing` subpath. react-core's `vitest.setup.ts` imports it through that
subpath rather than by relative path, so the package's own suite proves the export an app
resolves exists; the template's setup file makes the same call.

It reproduces what `ConfirmDialog` depends on, each point measured against Chromium's own
implementation: Escape fires a cancelable `cancel` at the topmost open modal and closes it
unless the event is cancelled; an Escape `keydown` whose default was already prevented — a
`Combobox` inside the dialog closing its option list — is not a close request; and a modal
removed from the document while open has left the top layer. It states on the function what
it does not reproduce: focus moving into the dialog and back to the opener, the inert page
behind it, the backdrop, event timing, an Escape whose propagation was stopped, and `close()`
on a dialog that is not open. Those are the Playwright suite's, in a real browser.

It is a no-op where `HTMLDialogElement` is absent and where `showModal` already exists, so a
jsdom release that implements the modal API retires it without anyone editing a setup file.

### A subpath, not the root

The root export is what app source composes and what the component catalog documents. A
test helper there would be importable into a production module with nothing to say it does
not belong, and would sit in the list every agent reads when it looks for a component. The
subpath keeps it out of both: it cannot arrive by extending an existing root import, and
reaching for it is a visible, greppable act.

This is not the deep import the boundary refuses. That rule refuses package **internals** —
`@terpjs/*/src/*` and `@terpjs/*/dist/*`, paths the package never promised — and a subpath
declared in `exports` is published surface with the same stability promise as the root, as
`./layout.manifest.json` already is. The lint needs no change: its pattern does not match a
declared subpath, and a setup file at the frontend root is outside the `src/**` scope it lints.

**The subpath imports nothing from the package, and that is held.** react-core's stylesheet
reaches the page as a side effect of its component modules, which is guaranteed only because
the package has one entry point into those modules and declares no `sideEffects` —
`markers.test.ts` pins both. A second code entry that reached a component would be a way to
render one without its styles. That test used to assert a single code entry outright; it now
asserts that every code entry other than the root imports nothing from the package, so the
testing subpath cannot grow into a second way in without the suite saying so.

### A function, not a side-effect import

`installDialogPolyfill()` in a setup file says what it does. A bare `import
"@terpjs/react-core/testing"` would be an effect with no name: a reader of the setup file
could not tell what it installs without opening the package, and nothing on the line would
mark it as load-bearing. Importing the module does nothing, so it is safe wherever it is
imported.

## Alternatives not taken

- **Copy the block into the template.** Two copies of platform-emulation code, one of which
  every app freezes at the version it was rendered from. The Escape behaviour added here is
  the proof: it would have reached react-core's copy and not the other.
- **Make `ConfirmDialog` fall back when `showModal` is missing.** Every current browser
  engine has it, so the fallback would exist only for a test environment — and where it did
  run in a browser, it would silently render a dialog with no focus trap and a live page
  behind it. That is a quiet downgrade of an accessibility contract, the opposite of failing
  closed, and a unit test would then exercise the fallback rather than the path users take.
- **A separate `@terpjs/testing` package.** Another lockstep package, a registry entry and a
  template dependency, for code whose reason to change is always a change in one component of
  this one. It belongs beside that component.
- **A vitest preset from react-core** that the template's config spreads. It would move
  configuration the app owns into the package and hide what runs at setup. With one thing to
  install, a named call is the smaller surface.

## Consequences

- A generated app's unit test can open a `ConfirmDialog`, confirm it, cancel it, or press
  Escape, and see what a browser would do. An app whose setup file predates this receives it
  with `copier update`; one whose setup file has diverged adds the import and the call, which
  react-core's README shows.
- `template-acceptance` drops a probe that renders a `ConfirmDialog` flow into each rendered
  variant and runs the app's own `npm test` against the packed tarballs. The template ships no
  screen that asks for a confirmation, so there is no shipped test to run in its place.
- The subpath is published surface. Adding to it is a decision about what an app's test
  environment needs from this package, taken with a reader for each export — the same bar as
  the root.
- A production module that imports `@terpjs/react-core/testing` is not refused by the lint
  today. It would do nothing in a browser, which has `showModal`; refusing it outside test
  files is a rule for the boundary package to take on, not something this change needed.
