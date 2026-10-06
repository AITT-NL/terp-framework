# 0175 — The frontend boundary does not stop at the module tree

- **Status:** Accepted and implemented (2026-10-06). Every rule in `terpBoundaries()` covers all
  app-authored `src/**`, in every script extension; code outside the modules may not import
  from one; a stylesheet is refused whether imported or loaded through `import()` /
  `import.meta.glob`; the app's own bootstrap may import the token pipeline's three stylesheets,
  by exact specifier, and no other. Held by `packages/frontend/eslint-boundaries/src/index.test.js`
  ("holds app source outside modules/ to the same boundary", "holds every script extension
  under src", the cross-module and bootstrap cases, the dynamic stylesheet cases, and "lints the
  template's own bootstrap clean"), and by `budget.test.js` for the widened extensions.
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
`BOUNDARY_SPEC.appFiles` (`**/src/**/*.{ts,tsx,mts,cts,js,jsx,mjs,cjs}`). None of these rules
is about a directory: a raw `<button>` is as unthemed in `src/diagram/` as in a module, and
`eval` is as dangerous. Nor is any of them about an extension. Every script extension the
bundler loads is listed, because a `.jsx` or `.mts` helper left out would make renaming a file
the same ungoverned exit that moving one was. The escape-hatch budget counts markers in the
same extensions (`BOUNDARY_SPEC.sourceExtensions`), so a marker in a `.jsx` file is budgeted
like any other.

**The module-shape rule reads the module tree for itself, in both directions.**
`no-cross-module-imports` is about what a module is. A module never imports a sibling, as
before. And code outside every module never imports from one: shared code is what modules
depend on, never the other way round. Without that second half, a file in `src/shared/` could
re-export `modules/billing/internal/secret`, and a sibling module could import the shared file
and reach billing's internals with no finding, because no path it named was a sibling's. A
module importing shared code stays legitimate. The bootstrap discovers the modules with
`import.meta.glob("./modules/*/module.tsx")`, which is not an import declaration, so
composing the app is untouched; a hand-written static import of a module from `main.tsx` is
refused like any other.

**The bootstrap imports the token pipeline and nothing else.** The app's own
`src/main.{ts,tsx}` is the one file that may import stylesheets, and only three, named by exact
specifier: `@terpjs/contract/tokens.css`, `./house-style.css` and `./theme.css`. They are the
pipeline's three layers: the framework's palettes, the house style a tool manages, and the
app's own overlay. A library's stylesheet is refused there as anywhere else, because a global
sheet from a package paints outside the palettes and outside what the contrast gate measures.
Every other rule applies to the bootstrap as to any file, deep imports included. Three details
keep the allowance exactly that wide:

- *Exact, in letter case too.* ESLint matches a `no-restricted-imports` glob group in any
  letter case, so an allowance written as negated globs let `./THEME.css` through as
  `./theme.css`. The bootstrap's stylesheet refusal is a regular expression instead, matched
  case-sensitively: a specifier ending in a stylesheet extension, in any case, is refused
  unless it is exactly one of the three. `./theme.css?inline`, `../src/theme.css`,
  `./sub/theme.css` and `some-lib/theme.css` are each one edit from an allowed name, and each
  is refused. Everywhere else the declared glob group stays, and refuses every case.
- *The app's own bootstrap.* `**/src/main.{ts,tsx}` alone also matches a `main.tsx` a module
  nests under a `src/` of its own, so the bootstrap block ignores `**/modules/**` and
  `**/src/**/src/**`.
- *TypeScript only.* `bootstrapFiles` names an allowance, so it stays as narrow as the file the
  template ships. A bootstrap in another extension meets the stricter rule.

**A stylesheet is refused however it is loaded.** `import("lib/style.css")` and
`import.meta.glob("./styles/*.css")` load a stylesheet without an import declaration, so
`no-restricted-imports` never saw them. Two `no-restricted-syntax` selectors refuse them: an
`import()` whose specifier is a string or template literal ending in a stylesheet extension
(with or without a `?query`), and an `import.meta.glob` whose pattern, or a pattern in its
array form, names one. Both read the extensions off `BOUNDARY_SPEC.styleImportPatterns`, and
both are attributed to `frontend/no-style-imports`, so the catalog's one marker waives either
spelling. That rule's catalog entry names `no-restricted-imports` as the reported rule. A second
reporter attributed by its message is how the adapter already realises
`frontend/generated-client-only` (`no-restricted-globals` and `no-restricted-syntax`) and
`frontend/no-dom-html-injection` (its own rule and `no-restricted-syntax`). Nothing that
consumes the attribution reads `reported_as` as the only path: the evaluated-rule inventory
lists catalog ids, not reporters, and the findings envelope, the corpus, the scorecard and the
opt-out parity all attribute through `catalogRuleId`.

**`BOUNDARY_SPEC` says what is true.** `moduleFiles` is gone. `terpBoundaries()` read it for
the module-scoped block, and that block is what this decision removes, so after this change
nothing reads it and it would describe a scope that no longer exists. `bootstrapFiles`,
`bootstrapStylesheets` and `sourceExtensions` take its place.

**The test that asserted the gap asserts the opposite.** It is joined by tests that pin each
part of this decision so that loosening it fails: every script extension held; a helper
importing into a module refused, a module importing shared code allowed, a sibling import still
refused, the bootstrap's `import.meta.glob` left alone; the bootstrap's three allowed, and each
near-miss above refused in the bootstrap, the same sheet refused from a helper, a nested
`main.tsx` refused, a deep import in the bootstrap refused; `.CSS` refused everywhere; the
dynamic spellings refused, attributed and waivable. Each was checked against the mutation it
exists for: an allowance by shape (`**/theme.css`), the case-insensitive negated globs, a
bootstrap block without the deep-import group, the allowance over `**/*.{ts,tsx}`, the bootstrap
block without its ignores, the dynamic selectors removed, and the cross-module rule returned to
modules only. And the template's own bootstrap, with every optional line its Jinja tags wrap,
lints clean: that keeps the allowance exactly as wide as the bootstrap a generated app starts
from.

## Consequences

**Adopting this release can fail an app's lint, and that is the point.** It is the same
consequence ADR 0136 accepted. A helper folder that styled itself, a page component beside
the modules that reached for `fetch`, a `.jsx` file nobody linted, or a shared file that
imported from a module was always outside what the app declared it held. The fix is what it
always was: compose the react-core primitives and the generated client, move what two modules
share out of either of them, or justify the exception with a marker under the budget.

**A specifier the lint cannot read is not resolved.** `import(name)` with a computed string
names no stylesheet until it runs, and no rule here evaluates code. That is the limit of every
import rule in this package, not a new one.

**Two things remain open, and they are named here so they are not mistaken for closed.**

- `theme.css` and `house-style.css` are plain CSS. A rule there can target any selector, a
  library's class names included. ADR 0158 says "a theme file carries tokens, not component
  rules", and nothing enforces it. That is the next door. A stylesheet check that admits only
  custom-property declarations under the theme selectors would close it.
- A full-screen workspace for a canvas, the case that surfaced this, is still not buildable
  inside the pattern. That is a gap in the framework, to be closed with a page and a primitive
  under ADR 0099, not with an exemption. It gets its own ADR.

**The Terp Standard follows.** The catalog's titles say "in app modules", and
`frontend/no-cross-module-imports` describes only the sibling direction. They describe the rules
and nothing reads them, so nothing here waits on a spec release. Their wording moves in
terp-spec's next one.
