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
preference the viewer's platform reports — and it is a declaration rather than an absence: an
absent key leaves whatever was already in force alone, including a bootstrap option, while
`"system"` is a value that goes through the same enum check, the same duplicate refusal and the
same output as any named palette. Nothing about it is exempt, and that is the point.

This paragraph said something else first, and the something else was wrong: that a file's
`"system"` *overrides* a passed option. It does not — §3.3 refuses a key declared twice
whatever its value, so declaring `"system"` in the file of an app that still passes the option
is a hard refusal at compose time, not a win. The test the sentence pointed at passed
`{ defaultTheme: undefined }`, which is no option at all, so it asserted the empty case with an
extra key spelled in. Recorded rather than quietly corrected, because a reader who had followed
the old sentence would have been sent to a refusal they were promised would not happen.

Where the resolution happens is the one implementation note worth recording. The palette is
mounted *outside* the router (`ThemeProvider` wraps `RequireAuth`, and therefore the router),
so `renderTerpApp` resolves the declaration itself in addition to the resolve inside
`buildAppRouter`. Two calls, one answer — but only while both are handed the same option set,
and that is a standing obligation the code does not enforce.

It was broken within a day. The navigation-groups amendment below added `navGroups` to the
router's explicit set and not to this one, so a groups conflict declared through `renderTerpApp`
was invisible from the call that runs first: the author fixed the density conflict it *did*
name, re-ran, and hit a second, different refusal — defeating the whole reason §3.3 names every
conflicting key at once. Fixed, and now gated by a test that declares two keys twice through
`renderTerpApp` and requires both in one message. Anything added to `BuildAppRouterOptions` and
forwarded at the bottom of that function belongs in the resolve at the top of it too.

`layout` and every option still travel down untouched, so a key added to the declaration later
reaches the router without being threaded through `renderTerpApp` first.

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


## Amendment (2026-08-24): the navigation groups, and why they went the other way

A navigation group spans modules — that is the reason groups exist and the reason no module can
own one. Which left the app's own code as the only place one could be declared, and therefore
left the **order of an app's navigation**, one of the few things about an app a person can see
without opening a screen, out of reach of anything that edits files. Same sentence as §2's three
shell choices, and same answer: `shell.navGroups`.

**It goes UNDER `shell`, and the palette above it does not.** Two additions on the same day
landing on opposite sides is worth explaining, because the answer comes from one test applied
twice rather than from taste. `shell` is where the keys whose VOCABULARY the standard fixes
normatively live. Palette names fail that test — which palettes exist is a stack's own to
publish, so `defaultTheme` follows `contract`'s half of the split. A navigation group passes it:
what an entry is called and what its fields mean is the same on any stack, and only the *values*
are the app's. It also lands next to `navPlacement`, which decides where that same navigation
sits, which is what a group of related keys should read like.

**`label` is a `string`, and `""` is how the file says `null`.** The runtime `NavGroup` types it
`string | null` and required, deliberately, so that having no label is a decision the declaration
states rather than a key someone forgot. The document has to preserve that property with a
narrower vocabulary: the standard's own minimal validator has no way to express "string or null",
which rules out the direct translation. Optional-with-absent-meaning-none would have handed the
property straight back to omission. Required-with-`""` keeps it, and the resolver maps the two
spellings in one line.

**`id` is refused when empty here, and accepted when empty there.** `groupNav` says in a comment
that the empty string is a perfectly usable map key, and it is right: that function runs on every
render, where being total matters more than being strict. Declaring one is a different act with a
different audience — an authoring error with no legitimate transient form, a group nothing can
name on purpose. The same split §3 already draws between a render-time fallback and a
compose-time refusal.

**`id`, `label` and the required-ness are typed on the declaration interface**, unlike the shell's
three values. Not a lapse in §4's measured rule: that rule is about a value's TYPE, because a JSON
string never narrows to its literal and a union would stop an app's own file typechecking.
Presence is a different question and one `resolveJsonModule` answers accurately — an imported file
missing a label is a compile error naming the field, which is strictly better than the runtime
refusal. Both exist, because a declaration handed in at runtime gets only the second.

**Duplicate ids are not refused in the resolver**, and that is deliberate. `buildAppRouter`
already refuses them with a message this would only restate, so the router's check now reads the
RESOLVED list: one refusal covers a duplicate declared in the file and one passed as an option,
with one message. The resolver stays about the document's own well-formedness.

**Gates.** Twelve mutations, all red. Ten over the seam itself — the key missing from the shell
table, an empty id accepted, a missing required field reported as a type instead of as missing, an
unknown group field ignored, a fractional sort key accepted, the `"" → null` map dropped, the
conflict push removed, the router's duplicate check pointed back at the options, the shell handed
the options instead of the resolved list, and the groups missing from the explicit set the
resolver compares against. And the parity test was run against the real 0.26.0 schema: green
unmodified, red on each of three drifts, each naming the two sets.

Two of those mutations were caught only after the assertions that were supposed to catch them
were rewritten, and both are worth recording because both were tests that passed with the bug.
The first compared the rendered lists' `aria-label` and `aria-labelledby` **attributes** against
`""`, which an unmapped `""` never produces: it produces a label element containing nothing and an
`aria-labelledby` pointing at it, so the list claims a name and has none — invisible to an
attribute check and to a role-name query alike, since a list with an empty name and a list with no
name are indistinguishable to both. Counting the label elements is the form that sees it. The
second declared the groups in the order they were meant to render in, so with the sort key dropped
every group tied at zero, the stable sort kept declaration order, and the assertion was already
the answer. Only a declaration order the sort has to undo can observe the sort.


## Amendment (2026-08-24): the vocabulary is published, so a tool can read it from the app

The three amendments above make the document carry everything an operator's tool would want to
rewrite. They leave the tool with a problem the token layer already solved once: it has to know
what the keys and values ARE.

A tool that works from its own idea of the vocabulary gets it wrong in the one direction that
matters. §3.2 refuses a key this release does not read — deliberately, and at compose time. So a
tool pinned to a newer framework than the app it is editing writes a key in good faith and the
app stops starting, naming a key the tool was told to use. The inversion is the point: what a
tool may write is decided by the app's OWN pinned framework, not by the tool's.

So `@terpjs/react-core` publishes `layout.manifest.json` — this document's schema with the
per-stack value sets filled in — and exports it at `./layout.manifest.json`, which puts it in
every app's `node_modules` beside the resolver that enforces it. A tool reads the vocabulary out
of the app it is editing and cannot offer a key that app will refuse. This is the same artifact
ADR 0093 §4 published for tokens, for the same stated audience: "a Studio editor, an agent with
file access, and a human".

**It is hand-written and gated, not generated**, and the reason is the same one
`theme.themes.test.ts` gives for the theme union. Generating it would need a TypeScript loader in
a build step this package does not have — the token manifest is generated because its inputs are
JSON, and these inputs are `as const` literals. And half its content is not derivable from the
source at all: the titles and one-sentence descriptions an operator reads in a form are the part
a generator could never produce, and are the reason a form built from it is usable rather than a
list of camelCase keys. So the copy stays a copy, and `layout.manifest.test.ts` checks it — every
top-level key, every shell key, every enum, the contract ids, the group's fields and its required
set, the unknown-key refusal at all three levels, and a title, description and type on every
property. Plus the export subpath itself, because a rename would leave every other assertion green
while the published path 404s in the only place the file is ever read.

Getting the enums out of the resolver meant naming them: the top-level key set was an inline
`new Set([...])` inside the refusal that reads it, and is now `TOP_LEVEL_KEYS` beside the others.
Exporting them costs nothing in public surface — the only CODE entry point the `exports` map
publishes is `./src/index.ts`, which re-exports none of them, and the manifest subpath beside it
is JSON. (The first version of this sentence said the map publishes only `./src/index.ts`, which
the same commit had just made false by adding that subpath — the same edit that had to widen
`markers.test.ts`'s one-entry assertion. Two places, one claim, and the test was corrected while
the prose was not.)

Seven mutations, all red: the manifest offering two palettes instead of five, a shell enum value
the resolver would refuse, a contract id `buildAppRouter` cannot find, a shell key renamed away
from the resolver's, a property left with no title for a form to render, the document saying it
accepts unknown keys, and a group field the resolver reads that the manifest does not offer.


## Amendment (2026-08-24): what an adversarial review of the three above found

Six lenses over the diff, each finding independently verified against the files before being
acted on. Twenty-two held up. They fall into three kinds, and the third is the one worth
keeping.

**One behavioural defect.** `renderTerpApp`'s explicit option set omitted `navGroups` while
`buildAppRouter`'s carried it, so the two resolve calls did not receive the same options and a
groups conflict declared through the entry point apps use was invisible. Fixed above, in §
"Where the resolution happens", with the gate that would have caught it.

**One defect the amendments made load-bearing without touching it.** `ThemeProvider` read a
stored `"system"` as "nothing stored", so a declared `defaultTheme` overrode it on every reload:
a person picked System, the session honoured it, and the next load put them back on the app's
palette while the menu reported that palette as active. That was survivable while `defaultTheme`
was a bootstrap option a handful of apps passed; making `"system"` one of six values any app can
declare in a file made it the documented behaviour of a documented key — the key whose own
docstring says it applies "until a person chooses another". `readStoredTheme` now returns `null`
for the absent case, so a stored choice wins whatever it is.

**Four tests that passed with the bug, and they are the reason to run a review like this at
all.** The forwarding gate on `layout: options.layout` asserted the resolver's enum refusal —
which `renderTerpApp` now raises *itself*, before `buildAppRouter` is reached — so it stayed
green with the line deleted; it now asserts an unknown *contract*, which only the router can
refuse. `layout.manifest.test.ts` asserted that every property declares *a* type, never *which*,
and never compared the emptiness floors at all: retyping `navGroups` to an object and `order` to
a string left all eleven assertions green while the resolver refuses both by name — the precise
failure the manifest exists to prevent, inside the file that exists to prevent it. Its
`required` pair was compared against a copy of itself written in the test rather than against
the resolver (the one vocabulary literal never hoisted into a named constant; it is
`NAV_GROUP_REQUIRED` now). And a `router.test.tsx` comment named a mutation that test cannot
observe, because it passes no groups option for the resolver's explicit set to carry.

The rest were claims: an ADR sentence promising a precedence the resolver refuses, an
`exports`-map count made false by the same commit that wrote it, a mutation note naming a value
`data-theme` never holds, a `describe()` docstring attributing an older branch to a newer
change, a "five keys" tally already stale, two option docstrings enumerating a file's contents
without `navGroups`, one still carrying the "keep the two in sync" instruction this whole ADR
exists to retire, and a manifest description omitting the one refusal reachable by writing
values it calls legal (two groups may not share an id). All corrected, and where a claim could
be made true by a gate instead of by an edit, it was.

Ten mutations over the fixes, all red.


## Amendment (2026-08-24): the mark, as a path

Third and last of the things an app could only say in its own source, and the one with a tool
already waiting for it: an operator uploads a logo, and there was nowhere to put the answer
except that app's TypeScript.

`shell.brand` is two optional paths, `logo` and `logoDark`. **Paths rather than elements**, and
that is the whole reason it can be declared at all — a file is something a tool can put
somewhere, and a `ReactNode` is not. The bootstrap options stay `ReactNode` and stay legal, per
ADR 0009: an app that wants an inline SVG or a component keeps writing one.

**The dark counterpart is declared, not derived.** A mark with fixed colours cannot survive a
dark background and nothing in this package can tell whether a given file can — a logo is an
opaque asset. So an app with a second file says so, and an app with one mark says nothing and
keeps it everywhere, which is the right answer when the mark does survive. Neither key is
required: requiring the counterpart would guarantee every app looks right on every palette and
would also force every app to claim a second asset it may not have.

**The refusal lives in the router, not the resolver**, and it is the first key where that is
true. Every other doubly-declared key is refused by `resolveLayoutDeclaration`, whose message
names both values so a reader can see which is which. Here the two sides are a path and a
rendered element, which are not comparable — there is nothing to print for the code side but
the fact that something was passed. So the check sits beside the duplicate-nav-group refusal,
where both halves are visible, and names the slots instead of pretending to compare them.

`alt=""` on the rendered mark, deliberately. The shell renders the app's title beside it, so a
name on the image has a screen reader announce the app twice — which is also what the template's
own commented example always did, and what an app hand-writing the option should do.

The template's comment is the part worth reading. It showed `logo: <img src="/logo.svg" alt="" />`
as a commented-out example, which is exactly the shape a tool cannot write: to set an app's logo
from outside, something would have had to edit JSX. It now shows the two lines of JSON instead.

Nine mutations, all red: `brand` dropped from the shell's key table, an empty path accepted, an
unknown slot ignored, the resolved brand discarded, the shell handed the option instead of the
declared path, the mark given an accessible name, the duplicate refusal disabled, and the
manifest dropping a slot and a floor.
