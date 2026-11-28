# 0223 — Type and shape have roles, as colour does

- **Status:** Proposed on 2026-11-27. Held by `packages/frontend/react-core/src/roles.test.ts`
  (each role is read by exactly the rules recorded here, none of them reads the scale step
  directly any more, and every default is a reference to the step those rules read before),
  `packages/frontend/contract/src/tokens.manifest.test.js` (the manifest records a reference as
  the sheet declares it), `apps/workbench/visual/computed.spec.ts` ("the type and shape roles
  resolve to the scale until a theme sets them, and each moves only its own readers") and, for
  "nothing renders differently", the unchanged screenshot baselines.
- **Date:** 2026-11-27.
- **Relates:** [ADR 0093](0093-semantic-token-layer-and-named-themes.md) (the semantic colour
  layer this gives type and shape), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (a restriction that removes a capability is a defect in the restriction),
  [ADR 0169](0169-a-page-is-composed-from-the-shape-of-its-data.md) (no style variant per
  block, which this keeps), [ADR 0094](0094-attribute-keyed-styling.md) (why an app's
  `theme.css` can already override any framework rule), [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md)
  (`font-src 'self'`), and in terp-studio ADR 0015 and ADR 0057 (a house style is token
  overrides, drafted from a description).

## Context

Apps built on Terp read as one app in different colours. The colour layer has been semantic
since ADR 0093: a house style or an app's `theme.css` sets the brand, the canvas, the surfaces
and the ink, and every component follows. Type and shape never got that layer. What an
interface is recognised by, after its colours, is its headings and its corners, and in both the
vocabulary offered a scale and nothing on top of it:

- **One typeface.** `--font-family-sans` is set on the shell's roots and on the `heading`
  component, and every other title inherits it. A heading face distinct from body text, the
  commonest way a brand shows in an interface, could not be declared.
- **One weight for two jobs.** Headings share `--font-weight-semibold` with badges, table
  headers, a figure's value, a message's title, the active navigation item and the selected tab,
  so a lighter heading weight could not be set without thinning all of those with it.
- **A radius scale read step by step.** Buttons, fields, the navigation's items and the menu
  trigger read `--radius-md`; so do alerts, toasts, tiles and code blocks. Cards, the data
  frame, charts and dialogs read `--radius-lg`, and so does a badge. Moving `md` to give the
  buttons a pill shape rounded the alerts with them, and moving `lg` to square the cards squared
  the badges. A shape language, controls one way and containers another, could not be said.

What could be done was the quiet thing: an app's unlayered `theme.css` beats any rule in the
framework's sheet (ADR 0094), so a selector on a react-core marker restyles a component. Nothing
checks such a rule, its contrast is measured by nobody, and it breaks without a word the day the
marker moves. In ADR 0103's terms, looking like one's own organisation is a capability, the
vocabulary limited it, and the only route around the limit was a silent one. Both are what that
ADR calls defects.

## Decision

### 1. Four role tokens join the contract

Each is theme-invariant, declared once in `:root` like every type and shape token, and each
defaults to a **reference** to the scale step its readers used before:

| Token | Default | Read by |
|---|---|---|
| `--font-family-heading` | `var(--font-family-sans)` | everything that names a page, a section, a dialog or the app: `heading`, `page-title`, `card-title`, `dialog-title`, `hubcard-title`, `empty-state-title`, `error-state-title`, `dataview-title`, `appshell-brand-title`, `login-title`, `admin-section-title` |
| `--font-weight-heading` | `var(--font-weight-semibold)` | the same, except `login-title` and `admin-section-title` (below) |
| `--radius-control` | `var(--radius-md)` | what a person presses or types into: `button`; `input`, which every field wears (Input, Select, Textarea, Combobox, DatePicker, DateTimeInput); the multiple combobox field; `menu-trigger`; the navigation's links; the icon buttons of the app header, the toolbar's layout switch, the pager and the calendar header; the inline row action; the sequence bar's links; a calendar day; the skip link |
| `--radius-container` | `var(--radius-lg)` | what holds content on the surface ladder: `card`, `page-summary`, `canvas-host`, `login-card`, `profile-card`, `hubcard-body`, the full DataView's frame and its header's corners, `dataview-card`, `empty-state`, `error-state`, the chart frames (`trend-chart`, `bar-chart`, `proportion-bar`), `stat` and the headline in a group, `dialog`, `popover-panel`, `combobox-list` |

A role set by a house style or `theme.css` separates its readers from the scale:

```css
:root {
  --font-family-heading: ui-serif, Georgia, "Times New Roman", serif;
  --radius-control: var(--radius-full);
  --radius-container: var(--radius-sm);
}
```

### 2. A reference, not a copy

The defaults are `var()` references, not the values they resolve to, for three reasons:

- **Nothing renders differently.** Every reader computes the value it computed before, by
  construction rather than by coincidence.
- **A style that already moved the scale keeps moving everything it moved.** A house style that
  set `--radius-lg: 0.25rem` for squarer cards before this existed still squares them, because
  the container role still points at `lg`.
- **Setting a role is the one way to separate.** Until a role is set, its readers move with the
  scale as the root declares it. The scale stays the instrument for moving everything at once.

A reference is resolved where it is declared, on the root. A step declared again lower in the
document, which only an unlayered rule in `theme.css` can do (a component's CSS Module admits no
custom property), moves the elements that read that step there and no longer a role's readers:
a sub-tree that wants its controls or containers to differ sets the role there as well. Nothing
in the framework declares a step below the root, and a house style declares every token on it.

The manifest publishes a reference exactly as the sheet declares it (`var(--radius-md)`), so a
consumer that scopes the shipped values onto an element, such as the Studio's preview, gets the
same cascade the app does.

### 3. What stays on the scale

A role names one of the two shapes a shape language is made of. The rest keep their step:
alerts, toasts, code blocks, tiles, list rows, skeletons, the selection bar, the brand box and a
hub card's icon keep `md`; a badge keeps `lg`; the small parts keep `sm`, such as a tab's top
corners, menu items, a combobox's options and tokens, the tooltip, an inline link and the icon
buttons inside a field, a card or a toast; avatars, meters and dots keep `full`. Moving the scale
still moves all of them.

Two headings keep their weight while taking the heading face. `login-title` is set bold, a step
heavier than the headings that take the role, and `admin-section-title` takes the browser's bold
for an `h3`. Moving either to the heading weight would repaint the sign-in screen and the
access screen in every app today, which this decision does not do; both are recorded by name in
`roles.test.ts`, so bringing them onto the role is a visible, re-baselined change rather than a
drift.

### 4. A face is a font stack, and an app's own face is its own file

A heading family is a font stack, and the browser takes the first face in it that it finds. A
stack of faces the reader's system may have needs nothing loaded, and it ends in a generic family
(`serif`, `sans-serif`, `system-ui`) that every system resolves: `ui-serif` and `ui-rounded` exist
only on some platforms, so `ui-serif, Georgia, "Times New Roman", serif` falls through to the next
face where they do not. An app's own typeface is a same-origin file: the
`.woff2` in `frontend/public/fonts/`, an `@font-face` in `theme.css` naming it by its path, and the
role naming the family. The document's policy admits fonts from the app's own origin only
(`font-src 'self'`, ADR 0104), so that route needs no change to it, and a font service's URL is
refused in the browser, as it should be: a font fetched from a third party on every page view is
egress nobody reviewed.

A house style can name a family and cannot load one: Studio refuses `url(` in a token value
(terp-studio ADR 0015), deliberately. A face the organisation wants in every app is a file each
app ships, in a change that goes through the gate and the diff.

## What it does not do

- **No variant per block.** ADR 0169 §1 stands: a role is app-wide, so within one app every card
  still looks like every other card, and emphasis is still a ranking the framework owns.
- **No colour, and no change to the contrast gate.** The roles are type and shape. The gate
  measures colour pairs and is unchanged; a heading weight lighter than the shipped one reads
  less firmly at small sizes, which no pairing records, so the guide asks for the headings to be
  checked in every shipped theme.
- **No key in the layout declaration.** A type or shape role is a token, written where tokens are
  written: `house-style.css` by a tool, `theme.css` by the app. The contracts in terp-spec do not
  change.
- **No refusal of the quiet route yet.** A selector on a react-core marker in `theme.css` still
  works. Refusing it is the natural next step now that the vocabulary can say what that route was
  used for, and it is a decision of its own: under ADR 0103 the capability comes first and the
  restriction after it.

## Consequences

- The Studio's house-style editor and its drafting turn read the token manifest (terp-studio ADR
  0057), so the four roles appear in both, labelled under typography and corners, once the Studio
  moves its framework pin. Nothing in the Studio has to change for that.
- `--radius-xl` has no reader, which nothing said until the radius family was tracked by
  `tokens.guard.test.ts` in this change; it is booked there by name, so wiring it or deleting it
  is a recorded decision.
