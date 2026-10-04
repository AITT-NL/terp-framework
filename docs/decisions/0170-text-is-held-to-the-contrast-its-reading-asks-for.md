# 0170 — Text is held to the contrast its reading asks for, in every palette

- **Status:** Accepted and implemented. Each text pairing's `reading` is declared in
  `packages/frontend/contract/token-pairs.json`; the floors are published by
  `scripts/build-tokens.mjs` as the manifest's `apca`. Held by `tokens.contrast.test.js` ("reads
  at Lc", "reaches 3:1 as a non-text pairing", "the neutral ramp runs one way"),
  `tokens.manifest.test.js` and `tokens.guard.test.ts`.
- **Date:** 2026-10-04
- **Relates:** [ADR 0093](0093-semantic-token-layer-and-named-themes.md) (the semantic layer, the
  manifest and the contrast gate this extends), [ADR 0167](0167-the-themes-are-named-for-the-time-of-day.md)
  (the palettes measured), [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) (the
  summary band and the surface ladder whose inks are measured here)

---

## Context

The contrast gate held every declared text pairing to WCAG 2.1 AA, and every pairing passed in
all five palettes. The dark palettes still read poorly where it matters most after the main
text: secondary text, links and badges. Measured with APCA, the lightness-contrast model the
WCAG 3 drafts use, night's lead line was Lc 44, its links 52 and its badges 41 to 51; evening's
links were 49 and twilight's 59. APCA's guidance asks Lc 75 of text a reader has to take in at
these sizes.

The gate could not see it because WCAG 2's ratio is known to flatter light text on a dark
ground: it measures luminance the same way in both polarities, so night's lead line passed at
6.4:1. GitHub's dark palette sets its secondary text near Lc 46 as well, so the level is
common practice. It is not readability.

Midday was close to APCA's guidance throughout, with small misses: badges at Lc 71 to 75 and
the pagination line at 72.

Two more findings came from the same measurement.

- **The control outline.** Every bordered control read the raw ramp step `--color-neutral-300`,
  at 1.4 to 2.4:1 against the surfaces controls sit on, in four palettes. The gate recorded this
  as an SC 1.4.11 failure in `BELOW_UI` and left it open, because fixing it would repaint every
  bordered control.
- **Night's main text.** It sat at Lc 101, near-white on near-black. That is the far end of
  comfortable: above it, halation grows for readers with astigmatism.

## Decision

### 1. Every text pairing says how it is read, and is held to APCA as well as to WCAG

Each text pairing declares a `reading`, and the gate holds it to that reading's minimum APCA
lightness contrast as well as to the WCAG ratio:

| Reading | Lc | For |
| --- | --- | --- |
| `body` | 90 | running text and values |
| `secondary` | 75 | short text a reader still has to take in: a label, a hint, a link, a badge, an error, a button label, the sidebar's navigation |
| `incidental` | 60 | a count, a position or a timestamp that orients rather than informs |

These are APCA's own levels. The manifest publishes them as `apca.minimumLc`, with the APCA build
they were measured under (`0.0.98G-4g`), because an Lc means nothing without its constants. The
gate reads the floors back from the manifest, so the published floor is the enforced floor. The
calculator is pinned to APCA's published reference values.

Every palette is held to the same floors, the high-contrast one included, because the reading
belongs to the text, not to the palette. Both models stay in force: WCAG 2 AA is the bar an app
is audited against, so APCA is added beside it and does not replace it. Placeholders and
disabled text are not declared pairings, and are not held to either model.

### 2. Text that is read does not use the subtle ink

`--color-fg-subtle` is the incidental reading: the DataView's result count, the pagination line,
a sequence's position, the sign-in separator. Three surfaces used it for text a reader acts on,
and they move to `--color-fg-muted`:

- the page band's lead line;
- a field's hint;
- a selectable tile's description.

A disabled tile's description fades with the rest of the tile.

### 3. The palettes move by the least change that reaches each floor

Each token that fell short is mixed towards white in a dark palette, or towards black in midday,
until it reaches its floor on every surface it is declared against. Mixing towards an extreme
keeps its hue.

- **Dark palettes:** `fg.muted` (with `neutral.600`, its primitive twin), `fg.subtle`,
  `fg.accent`, the four status inks and `sidebar.muted`.
- **Midday:** the four status inks, plus `fg.muted` and `fg.accent` by a hair.
- **Night's main text** is eased from Lc 101 to 95. This is a choice recorded here, not a floor:
  the gate holds no ceiling.

| Palette | Token | Was | Is |
| --- | --- | --- | --- |
| midday | `fg.muted`, `neutral.600` | `#475569` | `#445165` |
| midday | `fg.accent` | `#1d4ed8` | `#1a46c3` |
| midday | `status.success` / `warning` / `danger` / `info` | `#15803d` / `#b45309` / `#b91c1c` / `#0369a1` | `#137538` / `#a74d08` / `#aa1a1a` / `#0368a0` |
| twilight | `fg.muted`, `neutral.600` | `#d2c9e2` | `#e2ddec` |
| twilight | `fg.subtle` / `fg.accent` | `#c0b4d8` / `#c4b0ff` | `#cbc2df` / `#e3daff` |
| twilight | `sidebar.muted` | `#d2c9e2` | `#dbd4e8` |
| evening | `fg.muted`, `neutral.600` | `#b4c0d0` | `#ced6e0` |
| evening | `fg.subtle` / `fg.accent` | `#94a3b8` / `#60a5fa` | `#b0bbca` / `#b7d6fd` |
| evening | `sidebar.muted` | `#b4c0d0` | `#c9d2dd` |
| night | `fg.default`, `neutral.900` | `#f0f6fc` | `#e6ecf2` |
| night | `fg.muted`, `neutral.600` | `#9aa4b2` | `#d0d5db` |
| night | `fg.subtle` / `fg.accent` | `#8b949e` / `#58a6ff` | `#b3b9bf` / `#b5d8ff` |
| night | `sidebar.muted` | `#9aa4b2` | `#c7cdd4` |

The status inks move the same way, each until it reads at Lc 75 on its own tint, and the danger
ink on the surfaces error text sits on as well.

### 4. A control's outline is `--color-border-strong`, at 3:1

Every palette already shipped `border.strong` at the control outline's value (night's a step
lighter, contrast's black), and nothing read it. Controls read the raw step `neutral-300`
instead, and that step is also the scrollbar, disabled ink and a decorative outline.

Darkening the step was tried first, and it broke the ramp. In midday, `neutral-300` landed past
`neutral-400`, so a hovered field's border (400) turned lighter than its resting border. Disabled
ink became as dark as a control's edge. The semantic token takes the 3:1 instead, which is what
ADR 0093 meant a theme author to work with: "border colour", not "neutral-300".

| Palette | `border.strong` was | Is |
| --- | --- | --- |
| midday | `#bcc6d6` | `#848b97` |
| twilight | `#675e80` | `#8f89a2` |
| evening | `#475569` | `#727d8c` |
| night | `#484f58` | `#61676e` |
| contrast | `#000000` | `#404040` |

A hovered field's border moves to `neutral-500`, a step past the outline in every palette, and
the gate holds it there. The contrast palette's outline is `#404040`, the step its controls
already drew in: its black would have put the hover border back towards the ground. The two
control-boundary pairings now name `--color-border-strong` and pass, so `BELOW_UI` is
removed. Those two pairings were the only ones it was allowed to name, so a non-text pairing
below 3:1 is now a failure, not a gap to record.

### 5. The neutral ramp runs one way

A step moved for contrast must not pass its neighbour. The steps are read as an order: disabled
ink short of the label it disables, a field's label past the hint under it, a scrollbar's hover
past its rest. A value moved alone can invert those without a single pairing failing, which is
what the first drafts of §3 and §4 did in three of the four palettes they moved: the moved 300
passed its 400 in midday, twilight and night, and night's lifted 600 passed its 700.

The gate measures steps 100 to 900 in every palette and fails any step that turns back towards
the ground. Steps 0 and 50 are excluded because they are the surface and the canvas, and a dark
palette sets its canvas below its surface. Night's `neutral.700` and `neutral.800` are re-seated
between the lifted 600 and the eased 900: `#dbe0e6` and `#e0e6ec`, where they were `#c9d1d9` and
`#e6edf3`.

### 6. The danger button has a fill of its own

The danger button was filled with the danger ink, `--color-status-danger`, and labelled in the
surface's own colour. Nothing declared that pairing. A dark palette's danger ink is bright, so it
can be read on the app's ground, which made the label dark text on a bright red: Lc 44 in night
(5.65:1 by WCAG), 47 in evening and 57 in twilight.

Once §3 lifted the ink to read on its own tint, the button turned pale pink. That is readable,
but on a dark screen it is the brightest object, louder than the primary action, and it reads
as soft rather than destructive.

This is the shape ADR 0093 §5 refused for the accent: one token serving as both a filled surface
and an ink, two roles a dark palette cannot reconcile. The danger gets the same split:

- `--color-status-danger-fill` is the danger as a filled surface;
- `--color-status-danger-fill-contrast` is the only thing that may sit on it.

Every palette declares both, and the fill is a deep red with a white label: `#b91c1c` (Lc 85),
midday's danger button as it was, in every palette but contrast, which keeps its `#96000c`. The
pairing is declared as `danger-button-label`, read as secondary text.

## Consequences

- Every app looks different in the dark palettes. Secondary text and links are markedly
  brighter, and the hierarchy holds because the main text is still brighter and still heavier.
  In midday, control outlines are visibly darker and badges a shade deeper.
- An app's `theme.css` that retuned control borders by redeclaring `--color-neutral-300` must
  redeclare `--color-border-strong` now. The step itself still paints the scrollbar and disabled
  ink. A theme that recoloured the danger button through `--color-status-danger` sets
  `--color-status-danger-fill` and its contrast instead.
- A theme editor, or an agent writing an app's palette, holds it to the same two models from
  the manifest alone: the WCAG floors as before, and `apca` keyed by each pairing's `reading`.
- APCA's constants may change before WCAG 3 settles. Because the manifest names the build, a
  change of build is a visible decision, recorded as an amendment here, not an edit to a number.

## Alternatives considered

- **APCA alone.** Rejected. WCAG 2 AA is the conformance bar an app is audited against, and
  holding both costs nothing.
- **Lc 60 for secondary text,** the level some published palettes use. It lifts night and
  evening's links but leaves twilight's and evening's secondary text where it was. That is
  better than before, but not the readability this decision is for.
- **Darkening `neutral-300`.** Rejected for the reasons in §4.
