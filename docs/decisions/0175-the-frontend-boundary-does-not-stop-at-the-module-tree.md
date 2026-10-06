# 0175 — The frontend boundary does not stop at the module tree

- **Status:** Accepted and implemented (2026-10-06). Every rule in `terpBoundaries()` covers all
  app-authored `src/**`; the bootstrap may import the token pipeline's three stylesheets and no
  other. Held by `packages/frontend/eslint-boundaries/src/index.test.js` ("holds app source
  outside modules/ to the same boundary", the three bootstrap cases, and "lints the template's
  own bootstrap clean").
- **Date:** 2026-10-06
- **Relates:** [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md) (the same
  defect in the backend gate, closed there first), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (the boundary and the budget this widens), [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md)
  (an escape hatch on every page is the API), [ADR 0158](0158-a-quantity-is-shown-one-way.md)
  (a theme file carries tokens, not component rules)

---

## Context

ADR 0059 enforced the layout and component system "on the app-authored surface
(`src/modules/**`)". The flat config realised that as two blocks. The first, over every file
under `src/`, held the localization rules and the refusal of react-core's `data-terp` markers.
The second, over `**/modules/**`, held everything else: the raw elements, `style` and
`className`, stylesheet imports, deep imports, the generated client as the only way out, and
the security sinks — `innerHTML`, `dangerouslySetInnerHTML`, `eval`, `javascript:` URLs.

The gap showed up while costing out a full-screen canvas for an app whose main screen is a
diagram. A component in `src/diagram/` that imported a library's stylesheet and one of its own,
set `style` and `className`, rendered a raw `<button>`, called `eval` and wrote `innerHTML`
produced no finding. A module that imported it produced none either. The module rules held for
the module's own lines and for nothing it rendered.

This is the defect ADR 0136 closed in the backend gate three weeks earlier, where four security
rules skipped every file outside `modules/`. Its decision was that "a rule's scope follows what
it is about, and a security rule is not about a directory". The frontend config was not part of
that review, and it had the same shape: one block per directory rather than one per concern.
And as there, a test described the hole as intended behaviour:

```js
it("does not apply the module rules outside src/modules/", async () => {
  // A non-module file matches no config block, so the boundary rules never fire on it.
```

The cost was larger than the rules it skipped. ADR 0059's escape hatch is governed: a
`terp-allow-*` marker needs a reason and a line in the budget, and the budget is a ratchet.
Moving a file out of `modules/` needed neither, so the one governed opt-out had an ungoverned
twin that any app could take silently. ADR 0123 names where that ends: "an escape hatch used on
every page is not an escape hatch, it is the API, arrived at by erosion instead of by decision."

## Decision

**Every rule covers all app-authored source.** The two blocks become one, over
`BOUNDARY_SPEC.appFiles` (`**/src/**/*.{ts,tsx}`). None of these rules is about a directory: a
raw `<button>` is as unthemed in `src/diagram/` as in a module, and `eval` is as dangerous.

**The module-shape rule decides its own scope.** `no-cross-module-imports` is about what a
module is, so it reads the file's own path and returns nothing for a file outside every module.
Shared code beside the modules stays legitimate. It is now held to every other rule.

**The bootstrap imports the token pipeline and nothing else.** `src/main.{ts,tsx}` is the one
file that may import stylesheets, and only three, named by exact specifier:
`@terpjs/contract/tokens.css`, `./house-style.css` and `./theme.css`. They are the pipeline's
three layers: the framework's palettes, the house style a tool manages, and the app's own
overlay. A library's stylesheet is refused there as anywhere else, because a global sheet from
a package paints outside the palettes and outside what the contrast gate measures. Every other
rule applies to the bootstrap as to any file.

**`BOUNDARY_SPEC` says what is true.** `moduleFiles` is gone, because nothing reads it and it
described a scope that no longer exists. `bootstrapFiles` and `bootstrapStylesheets` take its
place.

**The test that asserted the gap asserts the opposite.** It is joined by the bootstrap's
allowance, a refused library stylesheet in the bootstrap, the bootstrap held to every other
rule, and the template's own bootstrap linted clean. The last one keeps the allowance exactly as
wide as the bootstrap a generated app starts from.

## Consequences

**Adopting this release can fail an app's lint, and that is the point.** It is the same
consequence ADR 0136 accepted. A helper folder that styled itself, or a page component beside
the modules that reached for `fetch`, was always outside what the app declared it held. The fix
is what it always was: compose the react-core primitives and the generated client, or justify
the exception with a marker under the budget.

**Two things remain open, and they are named here so they are not mistaken for closed.**

- `theme.css` and `house-style.css` are plain CSS. A rule there can target any selector, a
  library's class names included. ADR 0158 says "a theme file carries tokens, not component
  rules", and nothing enforces it. That is the next door. A stylesheet check that admits only
  custom-property declarations under the theme selectors would close it.
- A full-screen workspace for a canvas, the case that surfaced this, is still not buildable
  inside the pattern. That is a gap in the framework, to be closed with a page and a primitive
  under ADR 0099, not with an exemption. It gets its own ADR.

**The Terp Standard follows.** The catalog's titles say "in app modules". They describe the
rules and nothing reads them, so nothing here waits on a spec release. Their wording moves in
terp-spec's next one.
