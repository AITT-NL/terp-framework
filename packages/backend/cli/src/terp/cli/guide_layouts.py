"""The ``terp guide layouts`` topic: the slot-typed layout contracts, the archetypes and
what each body slot admits.

Its own module, as the security, testing, theming and design topics are:
``terp/cli/__init__.py`` is over the size cap and recorded in
``packages/backend/OVERSIZED.json``, a shrink-only ratchet.
"""

from __future__ import annotations

TOPIC = """\
Layout contracts (slot-typed layouts, ADR 0079)

- A layout contract is an OPT-IN ratchet above the page archetypes: not just "every
  routed view is framed", but "this archetype's body holds only these components".
  It is enforced two-layer and fail-closed, and every failure message tells you the
  contract, the slot, what was found, what is allowed, and the concrete fix — let it
  guide you.
- Opt in ONCE, in the file. `frontend/layout-contract.json` is the app's layout
  DECLARATION: the `terp/layout-contract` lint rule finds it on disk and `main.tsx`
  imports it, so one line governs both halves.

      frontend/layout-contract.json          -> { "contract": "standard" }

  Declaring the same fact in code as well — `renderTerpApp({ layoutContract: "..." })`
  — is REFUSED when the router composes, by name:

      frontend/layout-contract.json and the bootstrap options both declare "contract"
      (file: "standard", code: "standard"). Declare each in one place: the file is what
      a tool can read and rewrite, so prefer it and drop the option.

  (This recipe used to say "keep them in sync". It was the last copy of an instruction
  to maintain a duplicate, and the duplicate is now a startup error.)
  No config = no checks (fully backwards compatible; an existing app can switch later
  and fix screens by following the enforcement messages).
- The same file carries the rest of the app's declared shape, each key optional and each
  refused as a duplicate if it is also passed as a bootstrap option:
      defaultTheme            the palette the app opens on (terp guide theming)
      shell.density           "comfortable" | "compact"
      shell.navPlacement      "sidebar" | "header"
      shell.contentWidth      "full" | "measured"
      shell.brand             { "logo": "/logo.svg", "logoDark": "/logo-dark.svg" }
                              -- paths under frontend/public/, served from the site root
      shell.navGroups         [ { "id": "work", "label": "Workspace", "order": 1 } ]
                              -- label "" renders the group with no heading; a module's
                                 manifest names the group it belongs to
  A value off its enum, an unknown key, and a fact declared twice are three separate
  refusals, each naming the file, the key and the legal alternatives. The vocabulary is
  published as JSON at @terpjs/react-core/layout.manifest.json, so a tool (or an agent)
  can read what is legal instead of guessing.
- The "standard" contract governs the body slot of each archetype:
      HubPage      -> HubCard only (a card grid landing)
      OverviewPage -> DataView / ResourceList / ModuleNav / Stack / Card / Divider /
                      Text + the framework states (EmptyState / ErrorState /
                      LoadingState / Alert) and ConfirmDialog
      DetailPage   -> DetailList / DetailListGroup / Stack / Grid / Tabs / ModuleNav /
                      DataView / Card / Divider / Text + the same framework states and
                      ConfirmDialog
      FormPage     -> Stack / Grid / Card / Divider / Text + the same states and
                      ConfirmDialog: a form body is a container (Stack as="form"), never
                      a loose run of Fields
      SettingsPage -> Card / Stack / Divider / Text + the same states and ConfirmDialog:
                      Card sections, no collection
      SplitPage    -> SplitPane only: a list beside the record it selects
      DashboardPage -> Grid / Stack / Card / DataView / Stat / StatGroup / TrendChart /
                      BarChart / ProportionBar / StatusHistory / Timeline / Divider / Text +
                      the same states and ConfirmDialog: "how is the whole doing", its
                      figures in the summary band
      WorkspacePage -> ONE CanvasHost + the same states and ConfirmDialog: one canvas that
                      fills the screen. The host takes ONE canvas child (an svg, or a
                      canvas library's root) and sizes it to the whole box; what is
                      drawn ON it is yours. The trail is `parents`, as on DashboardPage
  Grid is not an overview-body component, deliberately: an overview body is a data
  collection, a grid of cards into each area is a hub, and sections of figures and charts
  are a dashboard — each has its own archetype. Heading is admitted nowhere: a heading in a governed body must OWN its
  section, and Card (boxed, or variant="plain" for no chrome) is how a section is
  owned; a bare heading with siblings after it is a grouping the check cannot see.
  The plain Page's BODY stays unconstrained — it is the sanctioned home for a bespoke
  screen. Only the slot's DIRECT children are governed: an allowed container's own subtree
  (a Card's body, a Stack's rows) is yours to compose — nesting content inside an
  allowed component is sanctioned composition, not an escape.
- Two rules belong to the page FRAME rather than to a body, so they hold on every page,
  the plain Page included (ADR 0169 §4):
      summary   -> Stat / StatGroup / StatusHistory / Badge / Text only: the band under
                   the title holds the page's own figures, nothing else
      headline  -> at most ONE figure per page is the headline (the brand-filled one);
                   the lint counts a page element's static JSX, the runtime the rendered
                   page, and both say the fix
- Compose a page from the shape of its data (ADR 0169). Decide what each block IS and use
  the component made for it — there are no style variants to pick, and the framework owns
  how each one looks:
      the figures the page is about   -> a StatGroup in the page's `summary`
      one figure, with its context    -> Stat: `delta` (the sentiment is yours to declare —
                                         more rejections is up and bad), `trend` (a
                                         sparkline), `target` (a range, drawn as a Meter)
      the figure that matters most    -> Stat `headline`, once per page
      facts about one record          -> DetailList
      values over time                -> TrendChart: mark "line", "area" or "columns",
                                         `comparison` for the period before
      categories compared             -> BarChart, ranked before it is passed
      a whole and its parts           -> ProportionBar, each part a word with its share
      how recent runs ended           -> StatusHistory, or `history` on a DataView column
      events in order                 -> Timeline: a record's history, newest first
      a collection                    -> DataView (the brightest object on the page)
      a section beside another        -> Grid template="2:1" ("1:2", "3:1", or the equal
                                         "1:1" / "1:1:1" / "1:1:1:1"), which collapses on a
                                         phone where columns={4} would clip
  Contrast is that ranking — the figures in their band, containers stepped back onto
  --color-bg-subtle, the data forward on the surface — so a block that should stand out
  is a different shape of data, not a custom colour.
- Pick the archetype by the question the page answers: a landing that only leads into the
  app's areas is a HubPage; one area's collection (how each one is doing) an OverviewPage;
  how the whole is doing a DashboardPage -- a landing that also carries the app's figures is
  one, as the hub preset scaffolds it; one record a DetailPage; entering a record a
  FormPage; settings a SettingsPage; a list beside the record it selects a SplitPage; work
  done on a surface (a diagram of nodes and connections, a plan) a WorkspacePage, whose one
  CanvasHost takes every pixel the shell leaves - a canvas never needs a style to be sized.
- Alternate framed and unframed blocks. The frame belongs to the data a reader works with:
  a collection, a chart and a lone figure sit on the surface, the collection brightest. A
  boxed Card steps back onto --color-bg-subtle, for a group of controls or one section of
  a record. Much of a page needs no frame at all: a StatGroup's figures, a DetailList, a
  Timeline, a line of Text, a titled section as Card variant="plain". A page that boxes
  every block in a Card reads as one object repeated, however good each block is.
- Enforcement (never lint-only):
      build time  -> the terp/layout-contract ESLint rule checks the static JSX
                     children of each governed archetype (npm --prefix frontend run lint)
      runtime     -> the archetypes verify the rendered DOM children (each sanctioned
                     component stamps a data-terp marker) and refuse the view, fail
                     closed — so dynamic children a linter cannot see are still governed.
- The one opt-out is the governed escape hatch: a justified
  `// terp-allow-layout-contract: <reason>` marker on the violating line, counted
  against the app's checked-in escape-hatch-budget.json (a ratchet). A recurring
  legitimate need should become a contract allowance, not an opt-out.
"""
