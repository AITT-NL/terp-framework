# 0093 — A semantic token layer, named themes, and an accent that is two tokens

- **Status:** Accepted
- **Date:** 2026-08-18
- **Relates:** Studio ADR 0015 — *Project styling themes* (the Studio writes a
  project's `theme.css`; this ADR is what that file can usefully say — it lives in
  the terp-studio repo, not here), and
  [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (app modules may
  not write `style` or `className`, which is what makes the token vocabulary the whole of
  an app's styling surface).

---

## Context

`@terpjs/react-core` styled itself from the primitive ramp directly: canvas was
`--color-neutral-50`, surface `--color-neutral-0`, border `--color-neutral-200`, muted
text `--color-neutral-600`. There was no `--surface`, no `--border`, no
`--muted-foreground`.

Three consequences followed, and all three were load-bearing.

A theme editor could only ever offer "neutral-300", never "border colour" — a list of
anonymous knobs with no meaning attached. Dark mode required inverting the entire ramp,
which `tokens.dark.json` literally did (`neutral-0` became `#1e293b`). And a third theme
was not expressible without re-deriving every mapping by hand, which is why exactly two
existed and why the claim that the vocabulary supported more had never been tested.

Meanwhile the vocabulary was also *invisible*. `tokens.json` is Style-Dictionary-shaped
and was not exported from the package; only the compiled stylesheet was. So a theme
editor hard-coded its own copy of the token list, an agent asked to "round the corners"
had to infer names out of `node_modules` with no way to tell which tokens are safe to
theme or which must stay legible against which, and a human had no list at all.

Two scales were missing outright rather than merely unnamed: z-index (`AppShell`
hardcoded 30/40/50, `Popover` 60, toasts 100) and breakpoints (the `768px` media query
duplicated verbatim in two components).

## Decision

**1. Layer semantics over the ramp; do not replace it.** `--color-bg-*`,
`--color-fg-*`, `--color-border-*`, `--color-interactive-*`, a `--color-sidebar-*`
namespace and a chart palette are added, alongside the scales that did not exist.
`--color-neutral-*` and the rest of the ramp **stay public**. An app that themed against
them is untouched.

This is deliberately the conservative half of a reversible choice. Deprecating the ramp
is cleaner and constrains future palette work less, but it breaks every app that themed
against it, and nothing about layering forecloses deprecating later. Layering first also
means the migration inside react-core can proceed component by component instead of as a
sweep.

**2. Semantic tokens carry explicit per-theme values, not aliases.** A semantic token
that resolved to `var(--color-neutral-200)` would look tidier and would chain the two
layers together permanently: the ramp could then never move without dragging every
semantic name with it, which is the opposite of why the layer exists. The cost is that
each theme states each value, and the completeness gate is what makes that safe.

**3. Themes are registered data, not discovered files.** `themes.json` lists every
shipped theme with its source, its appearance, its label and optionally a contrast floor
above AA. Registration is explicit because four things about a theme cannot be inferred
from its source file: which theme the OS dark preference selects, whether it reads light
or dark to native chrome, what contrast it promises, and what to call it. A
`tokens.*.json` on disk that nobody registered is a gate failure rather than a file that
silently does nothing.

Five themes ship. That number is not decoration: two themes cannot distinguish "the layer
works" from "the layer inverts a ramp", and a set of dark variants would not exercise it
either — so the set spans both polarities and more than one hue family.

**4. The token vocabulary is published as data.** `tokens.manifest.json` is generated in
the same run as the stylesheet, from the same sources, and exported from the package. It
carries every token's category and per-theme values, the theme list, and the
foreground/background pairings the contrast gate enforces. It is derived, never restated:
nothing in it can disagree with the stylesheet beside it, and CI diffs both.

This is the artifact a Studio editor, an agent with file access, and a human all needed,
and it is why no settings-mutation tool is required to make token editing legible to an
agent — an agent with a checkout simply reads it.

**5. The accent is two tokens.** `--color-brand-primary` means the accent as a *filled
surface*, and the only thing that may sit on it is `--color-brand-primary-contrast`.
`--color-fg-accent` means the accent as *ink or a boundary* against one of the app's own
surfaces.

This one was forced by measurement rather than chosen for tidiness. The single token was
serving both roles, and in a dark theme they are irreconcilable: the surface use needs a
value dark enough to hold a white label, the ink use needs one light enough to read on a
dark canvas, and no value satisfies both. The dark button label at 3.68:1 and the dark
selected tab at 3.98:1 were one defect with two symptoms, not two defects.

The alternative — brighten the accent and flip its label to near-black — fixes both with
no new token and no call-site edits, and was declined only because flipping a shipped
label is a visible identity change that the split makes unnecessary. A third option,
deepening the accent while keeping the white label, is ruled out on measurement: it fixes
the button (5.17:1) and drops the ink use to 2.83:1.

## Consequences

Every app repaints on upgrade. The four light status tones darken, the dark accent
surface deepens, and accent text and boundaries move to the ink token. Nothing changes
shape, and no app file changes: all of it arrives through the npm version bump, which is
the propagation lever this whole direction depends on.

An app that themed `--color-brand-primary` keeps controlling every filled accent surface
and no longer controls accent text. Setting `--color-fg-accent` alongside it restores a
single-knob accent.

The vocabulary is now a published contract in the strong sense — a manifest that tools
read — so removing or renaming a token is a breaking change in a way it was not when the
only consumer was the framework's own components.

Two token pairs still have the shape that made the accent fail:
`--color-interactive-selected` and each `--color-status-*-soft` are backgrounds whose
paired foreground is declared elsewhere. Nothing yet stops a later theme from pairing
them wrongly, and a token used as both a surface and a foreground is the shape to refuse
in review.

## Enforcement

The vocabulary is held by gates rather than by convention. Each of the following fails
silently in a browser rather than loudly at build time, which is why each is a gate:

- **Completeness** — every colour the base root declares is declared by every theme, no
  theme declares a token the base omits, and geometry stays root-only. A colour a theme
  forgets inherits the base value: one light-on-light element.
- **Contrast** — every declared pairing in every theme reaches WCAG AA for normal text,
  or the higher floor a theme declares. Held as a shrink-only ratchet; it is currently
  empty, and a theme added after it existed may not add to it.
- **`color-scheme`** — every theme block declares one matching its appearance, or native
  chrome the framework cannot restyle renders from the wrong palette.
- **Manifest parity** — the manifest names exactly the tokens the sheet declares, records
  the value each resolves to in each theme, and publishes the pairings the gate enforces.
- **Theme list parity** — react-core's `Theme` union, its theme array and its icon map
  match the published theme list in both directions.
- **Rendered accessibility** — axe over every component specimen in every shipped theme.
  Not redundant with the contrast gate: that one measures pairings somebody declared, and
  a new palette is exactly where an *undeclared* pairing goes wrong. It found five real
  defects in the themes added here that the static gate structurally could not see,
  including the accent's two roles.

Every one of these was verified by breaking it on purpose and confirming it fails. That
is the standard this vocabulary is held to, and it is not ceremony: two of the first three
gates written for it did not work at all, and the visual-regression gate turned out to
have been blind to realistic token edits since it was introduced — because its own
mutation check had used a change far larger than any real one.
