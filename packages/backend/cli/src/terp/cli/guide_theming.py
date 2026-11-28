"""The ``terp guide theming`` topic: tokens and palettes, the type and shape roles, the
brand mark and contrast.

Its own module, as the security and testing topics are: ``terp/cli/__init__.py`` is over
the size cap and recorded in ``packages/backend/OVERSIZED.json``, a shrink-only ratchet, so
a topic that grows moves out of it rather than growing it.
"""

from __future__ import annotations

TOPIC = """\
Theming and branding (design tokens, palettes, the brand mark)

- Use the shared tokens for palette, typography and spacing. For a custom screen, use a
  plain Page and import styles from "./Board.module.css". Apply className={styles.board}
  and define .board in that file. Global stylesheets belong to the bootstrap token pipeline.
- THE SHIPPED PALETTES, plus "system":
      midday  twilight  evening  night  contrast
  Named for the time of day they suit: midday is the light set, twilight a dimmed dark,
  evening the slate dark, night the near-black dark. `contrast` is a high-contrast light
  set. The active one is `data-theme` on <html>; the shell header's theme toggle offers all
  five plus "system" (follow the viewer's own platform preference) and persists the choice.
  `system` resolves to `night` when the platform asks for dark.
  `light`, `dark` and `midnight` are the EARLIER names of midday, evening and night. They
  are still accepted wherever a theme is named (defaultTheme, a stored choice, data-theme)
  and resolve to the new name -- but the theme toggle now writes the new names, so a
  selector in your own theme.css must use them: `[data-theme="dark"]` no longer matches.
- TO CHANGE HOW YOUR APP LOOKS, redefine tokens in `frontend/src/theme.css`. It is
  imported last and therefore wins the cascade. Declare only what you are changing;
  everything else falls back to the framework's value.

  The order is tokens.css, then house-style.css, then theme.css. The middle one belongs
  to your organisation's styling tool, which rewrites it wholesale — never edit it. To
  depart from a house style, declare the token in theme.css; nothing takes that back.

      :root { --color-brand-primary: #2563eb; }
      [data-theme="evening"] { --color-brand-primary: #60a5fa; }

  Per palette, use that palette's selector. A token with no palette selector is
  declared in `:root` and governs every palette at once — which is what you want for
  spacing, corners and typography, and usually not what you want for a colour.

  theme.css and house-style.css DECLARE TOKENS AND NOTHING ELSE, and the boundary lint
  reads both from src/main.tsx (ADR 0225): custom properties under :root or a palette's
  [data-theme] selector (and :root:not([data-theme]) inside a prefers-color-scheme group),
  @font-face for a face you serve yourself, and @media and @supports groups of those. A rule
  on a component's marker, a property that is not a token, !important or a url() in a token is
  refused with its line. When no token can express what you need, put the rule in a
  stylesheet of your own and import it in src/main.tsx under a justified
  `// terp-allow-no-style-imports: <reason>` marker, which the escape-hatch budget counts.
- THE PAGE'S BACKGROUNDS MOVE AS A SET (ADR 0169). `--color-bg-canvas` is the page,
  `--color-bg-subtle` the containers and chrome on it — boxed cards, hub tiles, the page
  band — and `--color-bg-surface` where data is read: tables, and charts and figures as
  they land. Every shipped palette declares all three, with subtle the midpoint of the
  other two. A token in theme.css does not recompute another, so a theme that moves canvas
  or surface redeclares subtle as well, usually as their midpoint; otherwise its containers
  keep the shipped tone, between two rungs the app no longer has.

      :root {
        --color-bg-canvas: #e8eef8;
        --color-bg-subtle: #f4f7fc;
        --color-bg-surface: #ffffff;
      }

  The page's summary band — the figures under its title — sits on its own token,
  `--color-bg-summary`, which every palette ships at its brand soft tint (night's a step
  darker, so subtle text clears AA on it). It is a value of its own, not a reference: a theme
  that moves `--color-brand-primary-soft` for a new brand moves `--color-bg-summary` with it,
  or the band keeps the shipped blue; a theme that wants a calmer band moves this one token
  and the tint the hub tiles share stays where it is.

- TYPE AND SHAPE CARRY AN IDENTITY, not only colour (ADR 0223). They have roles, each
  defaulting to the scale step its readers used before, so an app that sets none looks
  exactly as it did:

      --font-family-heading   the face of every title: a page, a section, a card, a
                              dialog, the app's own name in the shell
      --font-weight-heading   their weight (the sign-in title and an access screen's
                              section titles keep their bold)
      --radius-control        what a person presses or types into: buttons, fields, the
                              navigation's items, the menu trigger (a multi-line field: a
                              textarea, a list-box select or a multiple combobox, takes
                              it up to the container corner, and no rounder)
      --radius-container      what holds content: cards, the table's frame, charts,
                              figures, dialogs, popovers

  Set a role to give its readers a value of their own. Move the step under it in `:root`
  (`--radius-md`, `--radius-lg`, `--font-family-sans`, `--font-weight-semibold`) to move
  everything that reads that step, the roles included for as long as you leave them unset.
  A role is resolved on the root, which is where theme.css declares everything: a step set
  under :root or a palette's selector reaches the roles. (A step declared again below the
  root, in a stylesheet under the marker, does not reach a role's readers there: set the
  role there as well.)

      :root {
        --font-family-heading: ui-serif, Georgia, "Times New Roman", serif;
        --font-weight-heading: 500;
        --radius-control: var(--radius-full);   /* pill-shaped buttons and one-line fields */
        --radius-container: var(--radius-sm);   /* nearly square cards */
      }

  A component of your own takes the same roles in its CSS Module (`font-family:
  var(--font-family-heading)` on its title, `border-radius: var(--radius-container)` on
  its frame), so it follows a house style the way the framework's own components do.

  A FACE is a font stack, and the browser takes the first face in it that it finds, so end
  it in a generic family (`serif`, `sans-serif`, `system-ui`) that every system resolves.
  Faces a reader's system already has need nothing loaded, but not every system has the
  same ones: `ui-serif` and `ui-rounded` exist only on some platforms, which is why the
  stack above goes on to Georgia and then `serif`. YOUR OWN TYPEFACE is a file the app
  serves itself: put the .woff2 in `frontend/public/fonts/` and declare it in theme.css,
  above the role that names it:

      @font-face {
        font-family: "Brand Sans";
        src: url("/fonts/brand-sans.woff2") format("woff2");
        font-weight: 400 700;
        font-display: swap;
      }
      :root { --font-family-heading: "Brand Sans", var(--font-family-sans); }

  The app's security policy admits fonts from its own origin only (`font-src 'self'`),
  so a font service's stylesheet or file URL is refused in the browser: download the
  file, and check that its licence lets you ship it. A house style can name a family but
  never load one, because its values refuse `url(`; the file is each app's own reviewed
  change. A lighter heading weight reads less firmly at small sizes and no contrast
  pairing records that, so look at the headings in every shipped theme after changing it.

- TO SHIP ON A PALETTE OTHER THAN midday, name it in the layout declaration — never by
  restyling one palette to imitate another:

      frontend/layout-contract.json -> { "defaultTheme": "night" }

  Legal values are the palettes named above, plus "system". Passing `defaultTheme` as a bootstrap
  option as well is refused (terp guide layouts). Your organisation's styling tool may
  seed this key; changing it here makes it yours and later rollouts leave it alone.

  ONE more line for a palette that is dark. A person's own choice is read from
  localStorage before the first paint by `frontend/public/theme-bootstrap.js`, which the
  template wires into index.html — so a viewer who picks dark does not get a white flash
  on reload. A DECLARED default is not a person's choice and that script leaves it alone,
  so declare it on the document as well and the app opens in its own palette with no
  flash either:

      frontend/index.html -> <html lang="en" data-theme="night">

  Both halves are the same fact, in the two places that can each answer at a different
  moment: the attribute is there before anything runs, and the script overrides it only
  for someone who has chosen otherwise.
- THE BRAND MARK is a path, not JSX. Put the file in `frontend/public/` (Vite serves
  that directory at the site root) and declare it:

      "shell": { "brand": { "logo": "/logo.svg", "logoDark": "/logo-dark.svg" } }

  `logoDark` is picked automatically under a dark palette — most company logos have
  fixed colours and cannot survive one, and several of the shipped palettes are dark.
  The shell sizes the mark itself, in a box of `--shell-brand-size`; move that token in
  theme.css rather than scaling the image. An app that wants an inline SVG or a
  component can still pass the `logo` bootstrap option instead — declaring both is
  refused. The browser TAB mark is separate and cannot be declared: a browser reads it
  from `index.html` before any app code runs, so edit the <link rel="icon"> there.
- WHICH TOKENS EXIST is published, not guessed: @terpjs/contract ships
  tokens.manifest.json (every token, its category, its per-palette values, and whether
  a palette may vary it). Spacing, corners, typography, motion and z-index are
  theme-INVARIANT by design — declare them once in `:root`. An app whose spacing
  changed when someone switched palette is not what anyone means by a theme.
- CONTRAST is measurable, so measure it. @terpjs/contract holds every pairing the shipped
  palettes paint to two models (ADR 0170): the WCAG ratio, and APCA lightness contrast at
  the level the text's reading asks for -- Lc 90 for body text, 75 for secondary text a
  reader still has to take in (a label, a hint, a link, a badge), 60 for a count or a
  position. The manifest publishes both: each of `textPairs` names its `reading`, and
  `apca.minimumLc` the floors. If you override a foreground or a background, check its
  pairings against both rather than trusting the eye: WCAG's ratio alone passes light text
  on a dark ground that reads poorly. In module code the same split is `Text`'s tone:
  `muted` for anything read, `subtle` only for what orients.
- A CONTROL'S OUTLINE is `--color-border-strong`, held at 3:1 against the surfaces controls
  sit on. Move that token to retune the edge of every input, select and secondary button;
  `--color-neutral-300` is the scrollbar and disabled ink, not a border.
"""
