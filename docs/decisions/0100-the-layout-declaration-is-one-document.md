# 0100 — The layout declaration is one document, and the standard says so

- **Status:** Accepted
- **Date:** 2026-08-24
- **Relates:** [ADR 0079](0079-slot-typed-layout-contracts.md) (the contract this document
  opts into, and the two halves it kept from disagreeing),
  [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (declarative sugar must be
  opt-in and non-exclusive — the rule this is held to),
  [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) and
  [ADR 0086](0086-publish-the-terp-standard-to-pypi-and-npm.md) (the standard as one pinned
  release, which is why the schema lands in a spec release before this can gate against it),
  [ADR 0098](0098-archetypes-measures-and-the-density-island.md) (the three shell choices this
  moves into the document)

---

## Context

`frontend/layout-contract.json` has existed since ADR 0079 and has always governed something:
the `terp/layout-contract` lint rule walks up from each linted file, reads `contract`, and
enforces the slot table for it. The runtime half read **nothing** from that file. It took a
`layoutContract` string passed in TypeScript.

So a scaffolded app declared one fact twice, and the template said so out loud, three lines
above the duplicate:

```ts
// The slot-typed layout contract (runtime half; the lint half is layout-contract.json —
// keep the two in sync).
layoutContract: "standard",
```

"Keep the two in sync" is not a comment. It is an unenforced invariant with a human assigned to
it. Delete one side and the app keeps a build-time rule with no runtime check, or a runtime
check no lint agrees with, and nothing anywhere reports the mismatch. The same instruction was
written into `template/AGENTS.md`, `template/project/AGENTS.md.jinja` — where it briefs every
agent working in a generated app — the react-core README, and the option's own doc comment: four
copies of a sentence telling people to maintain a duplicate.

Separately, ADR 0098's three shell choices — `density`, `navPlacement`, `contentWidth` — shipped
as bootstrap options only. That made them reachable by editing code and by nothing else, which
put the shape of an app's shell out of reach of any tool that edits files.

## Decisions

### 1. The checked-in document is the single source for what it declares

The app imports it and passes it in (`renderTerpApp({ layout })`), so both halves read the same
bytes. `resolveLayoutDeclaration` collapses the document and the bootstrap options into one set
before anything reads them, so no consumer downstream can apply a different precedence.

**The file keeps its name.** It is the file the lint rule already looks for and every scaffolded
app already has one; renaming it would break the one consumer that worked, in exchange for a
nicer noun.

**Opt-in and non-exclusive**, per ADR 0009: an app that passes no declaration is on exactly the
path it was on before, and `layoutContract: "standard"` on its own remains legal and complete
for an app that would rather write code than check in a file.

### 2. The document carries the shell's shape, under `shell`

`contentWidth`, `density`, `navPlacement`. Grouped rather than flat because `contract` governs
the inside of a page and these govern the frame around it.

Every key is optional, and an absent key is **not a default** — it is the app declining to
declare, and the resolver leaves whatever was already in force alone. That matters most for
`density`, where ADR 0094 §4 already established that stamping a default would silently beat an
app's own `data-density` on `<html>`.

### 3. Three things are refused, fail closed, when the router is composed

Beside the duplicate-nav-group refusal that already lives there, and for the same reason: an
authoring error with no legitimate transient form.

1. **A value outside its enum.** A JSON file is not typechecked, so `"density": "compakt"` would
   otherwise reach the shell as an attribute value nothing styles — a declaration that silently
   does nothing, which is the failure this whole document exists to remove.
2. **A key this release does not read**, at either level. The cost is real and it is the right
   way round: an app pinned to a release is told the release cannot honour a key, rather than
   being told nothing while the key sits in the file looking effective.
3. **One fact declared twice — including when both sources agree.** That last clause is the
   tempting exemption and it is declined. Two sources holding the same value today is exactly
   the state that rots: one gets edited, the other does not, and the app silently keeps the
   stale one — which is precisely how the template arrived at "keep the two in sync". Whichever
   way a precedence went, someone editing the losing source would watch their change do nothing,
   and once the file is what *tools* edit, the tool becomes the one making a change that does
   nothing. Every conflicting key is named at once, with both values, rather than turning
   adoption into a fix-and-rerun loop.

### 4. The declaration's value types are `string`, and that was measured

`resolveJsonModule` types an imported JSON string as `string`, never as its literal. Declaring
the unions on `LayoutShellDeclaration` would therefore have shipped a template that stops
typechecking the moment an app filled the shell section in — the one thing the section is for.
Verified with a real `tsc` run before choosing rather than after: *"Type 'string' is not
assignable to type '"compact" | "comfortable"'"*, then re-verified that a filled-in file
compiles against the loosened type.

The consequence is worth stating plainly: **the runtime enum check is not defence in depth, it is
the only check that key ever gets.** The unions survive on `ResolvedLayout`, which is what the
shell is handed.

### 5. The vocabulary is normative in the standard, and parity-tested here

`layout-declaration.schema.json` (spec 0.26.0) is the stack-neutral schema, following
`restricted-surface.json`'s precedent for the split: `contract` is a plain string because which
contracts exist and what their slots admit is per-stack configuration, while the shell's
vocabulary is fixed normatively — a density means the same thing on any stack.

`tests/architecture/test_spec_catalog.py` holds this stack's resolver to those enums in both
directions. It is skipped while the pinned spec predates the schema, because the framework pins
one exact spec release (ADR 0086) and pinning an unreleased spec to satisfy a test is how a pin
stops meaning "a release we shipped".

### 6. No build-time validation of the document, and this is the reason

The ADR 0006 quadruple would put a build-time half beside the runtime refusal. It is **not**
built, and the constraint is concrete: `@terpjs/spec` is a *dev* dependency of
`@terpjs/eslint-boundaries`, so a lint rule cannot read the standard's schema in a consumer's
app. Validating at lint time therefore requires either making the standard a runtime dependency
of the lint package — a change to the consumption model for every app, which is not a side
effect to take on here — or a **third** copy of the vocabulary beside the schema and the
resolver, parity-tested like `BOUNDARY_SPEC` is.

Declined for now on the balance: the runtime refusal fires at compose time, which for a frontend
is the first `npm run dev` or the first page load, naming the file, the key and the legal values.
The marginal gain from catching it one step earlier does not currently pay for a third mirror of
one enum table.

What would change it: the standard becoming a runtime dependency of the lint package for its own
reasons, at which point the rule can validate against the schema itself with no copy at all.
Recorded rather than left as an absence, so the gap is a decision someone can revisit instead of
an oversight someone rediscovers.

## Consequences

- An app adopting the declaration needs `resolveJsonModule` in its frontend `tsconfig.json`; the
  template carries it, so existing apps pick it up through the scaffolding upgrade rather than
  by hand.
- The corpus is unchanged and the coverage ratchet stays empty. The rule did not change — an
  opted-in app's archetype body slots still admit only the contract's components — so no new
  corpus case is owed. The document's *validity* is a runtime control, which the corpus (a
  static-source contract) cannot express.
- A tool can now read and rewrite how an app's shell is shaped without writing that app's
  TypeScript. That is what the Studio's layout editing needs, and it is the reason to widen this
  file rather than invent another.
---

## Amendment (2026-08-24): the palette the app opens on

The decisions above moved three shell choices into the document because they were reachable
by editing code and by nothing else. `defaultTheme` was left out on the grounds that it is
appearance rather than layout — a real distinction, and the wrong one to act on. Which
palette an app *opens* on is among the most visible choices its operator makes, and leaving
it a bootstrap option kept it exactly as unreachable as `density` was the day before this
ADR. So it joins the document.

**It is a top-level key, not a `shell` key**, and that is the one shaping decision here.
The taxonomy argument is real but weak: a palette paints the frame and the page alike, while
`shell` is where the frame's geometry is declared. The deciding argument is the
portable/per-stack split §5 draws. `shell`'s defining property is that its vocabulary is
fixed *normatively* — a density means the same thing on any stack. Palette names do not:
which palettes exist is a stack's own to publish, exactly like which contracts exist. Putting
a per-stack string inside the group whose whole point is a fixed normative vocabulary would
make that group mean two things. So it follows `contract`'s half of the split instead — a
plain string in the schema, with the values recorded in the catalog entry's non-normative
`reference` field.

**The enum is the framework's own theme registry, imported rather than restated.** The list
already exists as `THEMES`: the array the theme control offers, the array `ThemeProvider`
validates a stored choice against, held to `@terpjs/contract`'s compiled stylesheet by
`theme.themes.test.ts`. Writing the palette names a second time in the resolver would have
added a third place a shipped palette could go missing from. Getting the import required
moving the names into `themes.ts`, a leaf module with no React and no DOM — importing
`theme.tsx` from the resolver would have pulled the icon set and the component stylesheet's
module-scope injection into a module whose entire job is to validate a JSON file, and into
the node-environment test that covers it.

Refusing an unknown palette rather than falling back is the same reasoning as §3.1 and worth
restating because the fallback is so available here: `data-theme="midnite"` matches no block
in the stylesheet, so the app renders the base palette and *nothing anywhere reports that the
file was ignored*. The standard's schema says so in its own words, so a consumer on another
stack inherits the obligation rather than the temptation.

**One reserved name.** `"system"` is portable — the app opens on whatever light or dark
preference the viewer's platform reports — and it is a declaration, not an absence: an absent
key leaves whatever was already in force alone, including a bootstrap option, while
`"system"` overrides one. Both are asserted.

Where the resolution happens is the one implementation note worth recording. The palette is
mounted *outside* the router (`ThemeProvider` wraps `RequireAuth`, and therefore the router),
so `renderTerpApp` resolves the declaration itself in addition to the resolve inside
`buildAppRouter`. Two calls, one answer by construction: the resolver is pure and total over
its inputs, and both calls receive the same declaration and the same options. What would
break that is resolving once and handing the router a *different* input set, so `layout` and
every option still travel down untouched — which also means a key added to the declaration
later reaches the router without being threaded through `renderTerpApp` first.

§6 is unchanged: still no build-time half, for the same `@terpjs/spec`-is-a-dev-dependency
reason, and this key does not move that balance.

**Gates.** Six mutations, all red, on the six lines that carry the key from the file to the
`<html>` attribute: the enum check, the duplicate check, the known-key set, the type check,
the value handed to `ThemeProvider`, and the palette's presence in the explicit set the
resolver compares against. The last two are the ones a unit test on the resolver cannot see,
and they are gated on the rendered `data-theme` attribute rather than on a throw — the
signed-out mount renders no shell, but it does mount the provider, so this is the one
declaration key whose effect is directly observable in the DOM. The spec parity test was run
against the real 0.26.0 schema (green) and against a drifted resolver (red, with the two key
sets named), rather than left to the skip it sits behind until the pin moves.
