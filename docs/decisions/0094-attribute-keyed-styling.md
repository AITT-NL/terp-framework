# 0094 — Attribute-keyed styling: base styles move from inline `style={}` to the injected sheet

- **Status:** Accepted
- **Date:** 2026-08-18
- **Relates:** [ADR 0093](0093-semantic-token-layer-and-named-themes.md) (the token
  vocabulary these rules consume), [ADR 0079](0079-slot-typed-layout-contracts.md) (the
  `data-terp` markers the rules key on), and
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (app modules may
  not write `style` or `className` — which this ADR does not loosen by one millimetre).

---

## Context

Every react-core component styled itself with inline `style={}`. The header of
`styles.ts` documented the trade in its own words: inline base styles keep tests able to
assert `element.style.background`, and the framework owning the cascade is what makes the
app-module prohibition enforceable — at the cost that `style={}` wins the cascade over
any author stylesheet, so every interaction-state declaration in the injected sheet
carried `!important`. Thirty-seven of them, each one a tax paid to a base style that
could not lose.

That trade bought something real while the component set was small and static. It
stopped being worth its cost for three reasons, in rising order of weight:

1. **The `!important` escalation is a one-way ratchet.** State-scoped rules cannot leak
   into resting styles, but they also cannot compose: a rule that must beat an inline
   style must beat *every* stylesheet forever, including the framework's own future
   rules. Each new interaction state made the sheet harder to reason about, not easier.

2. **The testability argument inverted.** Asserting `element.style.background` pins a
   component to *how* it is styled, not *what* it renders. The attributes the framework
   already stamps for the layout contract (`data-terp`, `data-variant`, `data-tone`,
   `data-selected`, `data-collapsed`) are the stable, semantic surface — a test that
   asserts `data-variant="primary"` survives any restyling that keeps the contract,
   which is exactly what a test should survive. The visual workbench (62 pinned
   baselines, `threshold: 0.02`, `maxDiffPixels: 0`) now covers what the style
   assertions actually guarded: the pixels.

3. **Inline base styles are the ceiling on the whole configurability story.** An app's
   `theme.css` could redefine token *values* and nothing else; a Studio editor past
   colour was unbuildable; `variant`, `size` and `density` were frozen constants because
   a prop that only swaps one inline object for another cannot be re-scoped, cascaded,
   or themed. Killing the ceiling requires the base styles to live where the cascade
   can see them.

## Decision

**1. Base styles move into `TERP_STYLES_CSS`, keyed on the attributes components already
stamp.** Selectors are attribute selectors — `[data-terp="button"]`,
`[data-terp="button"][data-variant="primary"]` — never class names. No `className`
appears anywhere, so the app-module `style`/`className` prohibition and its lint remain
byte-for-byte what they were, and `markers.test.ts` keeps scanning the sheet side
unchanged. `styles.ts` stays the single stylesheet module, because the marker inventory
pins that path as the one place selectors may live.

**2. No `!important` in migrated rules — the sheet is ordered by cascade layer instead.**
`@layer terp.reset, terp.base, terp.state, terp.motion;` A state rule beats a base rule
because of its layer, not its specificity and not its position in the file.

The obvious alternative — rely on interaction states being more specific, since they add
a pseudo-class — does not hold, and this was measured rather than reasoned about. The
shared focus ring `[data-terp]:focus-visible` and the primary button's
`[data-terp="button"][data-variant="primary"]` both weigh **(0,2,0)**: an attribute plus a
pseudo-class against two attributes. They tie, so source order decides, and the ring has
always been declared near the top of the sheet. The moment the primary button's resting
shadow moved out of `style={}` and into a rule in the same layer, the focused button
computed `rgba(15,23,42,0.06) 0 1px 2px` — its resting shadow, no ring — on the most
focus-relevant control in the package. With the ring in `terp.state` it computes
`rgba(37,99,235,0.35) 0 0 0 3px`. That regression is the thing `!important` was concealing
rather than fixing, and it would have recurred for every component whose base rule happened
to be declared after a state rule.

Two things stay **unlayered**, for the same reason: an unlayered author declaration beats a
layered one regardless of specificity. The density re-scoping must be unlayered or the
contract's own unlayered `:root` values would beat it and `data-density="compact"` would do
nothing. And an app's `theme.css` is unlayered, which means an app can override any
framework rule without `!important` — the restyling this phase exists to enable, arriving
as a property of the layering rather than as a second mechanism.

Each component's migration removes its own `!important`s in the same commit; the end state
of the sheet is zero.

**3. Enumerable props become data attributes; measured values stay inline.** `variant`,
`tone`, enumerated `size`, `selected`, `destructive`, `collapsed`, Stack's five props —
anything with a closed value set — becomes a `data-*` attribute with one rule per value.
Genuinely continuous or computed values stay `style={}`: Popover's fixed positioning,
`Icon`/`LoadingState` numeric sizes, DataView column pixel widths. That boundary is the
honest one — a computed position was never styling policy, and forcing it through
attributes would mint a rule per pixel.

**4. Density is a prop *and* tokens, not one or the other.** The contract declares live
density tokens (`--density-control-min-height`, `--density-cell-pad-y`,
`--density-cell-pad-x`) at their comfortable values, plus explicit
`--density-compact-*` counterparts — root-only geometry, like every other scale. The
sheet re-scopes the live tokens under `[data-density="compact"]`, so a `density` prop is
one stamped attribute on a subtree root (the shell for an app-wide default, an embedded
DataView for one table), and a `theme.css` can still move either value set app-wide. A
*comfortable island inside a compact subtree* is deliberately not expressible yet: it
needs a named comfortable copy of each live token, and vocabulary nothing consumes gets
retired by stated policy — it can be added the day something asks.

**5. The four rootless surfaces gain markers without gaining layout boxes.**
`ThemeToggle` and `LanguageSwitcher` (inline variant) and `UserMenu` delegate their root
to `Menu`, whose rendered root is `Popover`'s wrapper; `Menu` therefore accepts an
optional root marker, threaded to that existing wrapper (default stays `"popover"`), and
each control names itself (`theme-toggle`, `language-switcher`, `user-menu`) with
`data-variant` distinguishing `inline` from `stacked`. `Markdown` renders a fragment; it
gains a `display: contents` wrapper carrying `data-terp="markdown"` — no box is
generated, so blocks remain individual flex/grid items of any parent and the diff is
zero by construction, while descendant selectors become possible for the first time. A
real block wrapper that owns prose rhythm is a later, intentional change, not a side
effect of marking. None of these markers appear in any layout-contract allow table, so
slot behaviour is unchanged in both directions.

**6. Nothing about consumption changes.** No build artifact, no CSS export, no runtime
dependency. The sheet is the same injected `<style>` element it has been since it
existed; an npm version bump still delivers everything with zero app-file edits.

## Consequences

- Every component's rendered markup gains attributes and loses `style`; computed styles
  are identical, so the visual baselines are the proof of each step — every diff is
  intentional or zero, and the migration proceeds component by component, never as a
  sweep.
- Tests that asserted `element.style.*` move to asserting the attribute (the semantic
  claim) — the ~27 style-coupled assertions are the migration checklist. The
  `body.style.overflow` scroll-lock assertions are not styling and stay.
- Components become restyleable from a token file for the first time: a rule reads
  tokens, a theme moves tokens, and — new — an app-side stylesheet *could* target the
  same attributes. That door stays closed for app modules (ADR 0059 stands); it opens
  only for the framework's own sheet and, later, for Studio-written theme files if a
  future ADR says so.
- `Menu`/`Popover`'s `triggerStyle`/`panelStyle` props are exposed as the inline-style
  API surface they are; once `UserMenu` styles through its own marker they lose their
  last heavy consumer and should be narrowed in a later minor.
- The `styles.ts` header comment describing the inline-base trade is rewritten by this
  migration; this ADR is the record of why the documented choice was reversed.

## Enforcement

- `markers.test.ts` — the inventory grows with each migrated surface and
  `UNMARKED_STYLED_SURFACES` shrinks to empty; both directions stay pinned, and the
  stylesheet side still cannot re-supply a marker a component stopped rendering.
- `tokens.guard.test.ts` — every `var(--x)` the sheet consumes must be declared by the
  contract, so a token typo in a migrated rule fails the suite, same as it did inline.
- The workbench visual suite — zero-diff baselines per migrated component
  (`threshold: 0.02`, `maxDiffPixels: 0`), axe across all five themes, both contrast
  ratchets held empty.
- The pattern itself was verified by mutation at the first migrated component, `Button`:
  shifting a moved rule one ramp step (the ghost label, `neutral-700` → `neutral-600`)
  failed exactly the eight baselines containing a ghost button and nothing else. A gate
  verified with an easy case is verified for easy cases.
- The layering was verified the same way, in both directions: demoting the focus ring into
  `terp.base` before the button rules suppressed it on the focused primary button, and
  restoring it to `terp.state` brought it back. Note the first attempt at this probe used
  `element.focus()` and proved nothing — programmatic focus does not match
  `:focus-visible`. It needs a real `Tab`, and the computed value has to be read after the
  transition settles or it reads mid-interpolation.
