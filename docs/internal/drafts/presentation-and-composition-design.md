# Presentation and page composition — the proposal and the sequenced plan

> **Decision:** [ADR 0169](../../decisions/0169-a-page-is-composed-from-the-shape-of-its-data.md)
> (2026-10-03): every fork went the recommended way, and so did the three open points. This file
> was the proposal and is now the execution tracker; when it disagrees with the ADR, the ADR wins.
>
> **Audience:** platform/core team + agents. **Status:** decided; in progress.

The goal, in one line: a Terp page should have deliberate hierarchy — figures that read as figures,
the collection as the brightest object on the page, framed and unframed content side by side, an
accent used once — produced by the framework's vocabulary rather than left to whoever writes the
page, and themed exactly as everything else already is.

## Why this, and why now

The direction comes from the platform's owner, after comparing rendered pages: a Terp page is the
same object repeated, and nothing on it is louder than anything else. The framework should
*promote* contrast and variety in layout and styling — cards and text directly on the background in
combination, new ways to present key values and KPIs, the way BI dashboards and current product
interfaces do — while one theme and consistent styling still govern every app.

That is a product decision, and it is the premise of this proposal rather than one of its options.
What the proposal has to settle is how a framework whose ideology admits no flexibility in usage
patterns (ADR 0103) produces variety without becoming a menu of styles. In ADR 0111's terms it
constrains a **usage pattern** — "how a thing is done when the framework already offers a way to
do it" — and no capability: every page an app can build today stays buildable. Its one new
conformance rule (one headline per page, fork 5) sits beside the frontend's existing usage-pattern
rules — ADR 0059's boundary, ADR 0079's slot contracts — rather than among 0111's security
invariants, and the ADR should say so in those words.

A rendered study backs every option below: the current page, the alternatives, a catalogue sheet
per family of presentation, and two composed pages, built from react-core's own stylesheet and
tokens, in every registered theme and at phone width. It lives outside the repository; the
measurements quoted from it are restated here so this file stands on its own.

## What the references actually do

Taken for their mechanics, not their look.

**BI dashboards** (Power BI is the usual reference):

1. The visual is chosen by the **shape of the data**: one figure becomes a card, a figure against a
   target a KPI or bullet, values over time a line or columns, a ranking a bar chart, a share of a
   whole a stacked bar, many records a table or matrix.
2. **One theme file styles every visual.** A report formatted visual by visual is the report people
   call messy.
3. Every visual has the **same header**: title, optional subtitle, actions.
4. **Key figures sit at the top**, and a bigger tile means a more important figure.
5. **One set of filters** applies to every visual on the page.
6. **Conditional formatting** puts cues inside tables: bars in cells, status icons, shaded cells.

**Current product interfaces:**

1. Hierarchy comes from **type and space more than boxes**: a section heading sits on the canvas,
   unframed.
2. **Several surface levels** instead of one card colour.
3. **Asymmetric tiles in a strict grid.**
4. **One saturated accent per view**; everything else neutral.
5. **Large tabular numerals** over small muted labels.
6. Status as a **soft tinted fill and a word**, not a heavy border.
7. **Small data inline**: sparklines and bars inside rows.

**Not taken:** a free-positioned canvas, per-visual formatting panes, decorative gradients and
glass, a second accent per view. Each is a style an agent would pick at random.

## Where a page stands today (measured at 0.29.0)

1. **One object.** Card and the framework's other in-flow blocks — `hubcard-body`, `profile-card`,
   `resource-list-row`, `empty-state`, `dataview-card` and the full DataView's frame — are all a
   `--color-bg-surface` fill inside a hairline frame on the canvas, and Card, the HubCard body and
   the DataView card share the whole recipe: a `--color-neutral-200` border, `--radius-lg`,
   `--shadow-sm`. The "Cards" comment in `styles.ts` records this as the surface model. On a page,
   the only hierarchy is block order and heading text.
2. **Two surface levels, one of them unnamed.** The page ground is painted `--color-neutral-50` by
   the `body` and `appshell` rules. `--color-bg-canvas` holds the same value in every theme and sits
   on `UNREAD_TOKENS` in `tokens.guard.test.ts`, as does `--color-bg-raised`, which equals surface in
   the light theme (named `midday` since 0.31.0). Its canvas against surface measures 1.13:1.
3. **A figure is a title over text.** `Text` stops at `lg` and a Card title is `lg` semibold, so in a
   tile of label and value the label is the louder of the two. HubCard's `stat` line is the only
   place react-core gives a figure a slot of its own ("a lightweight dashboard", `HubPage.tsx`).
4. **Grids weigh every block equally.** `Grid` takes `columns` 1–4 or `auto` and has no `span`
   (`layout.tsx`). Fixed counts keep their count at every width by design — ADR 0097 §3 leaves
   reflow to `columns="auto"` and §4 gives responsive forms to `direction` and `gap` only — so a
   legal `columns={4}` row of figures clips at phone width (measured at 390px).
5. **The chart palette is published and unread.** `--color-chart-1..5` are on `UNREAD_TOKENS`, and
   `token-pairs.json` holds no chart pairing. ADR 0158 fixed the contract for charts and builds no
   kind until two observations name it.
6. **The guidance steers away from variety.** `terp guide layouts` says `Grid` "is a DETAIL-body
   component and not an overview one, deliberately", that "a grid of summary cards is a hub", and
   that `Card` is how a section is owned.
7. **The framework already shapes data it cannot draw.** The `sync` capability stores each
   `SyncRun`'s aggregates "so a stats view never pays a per-row `COUNT(*)`"
   (`capabilities/sync/models.py`), and `webhooks` keeps an append-only `WebhookDelivery` log — an
   `outcome` and a `response_code` per attempt. Both are a status per run over time, and react-core
   can show each run only as a badge in a table row. The Studio's project wizard meanwhile offers
   the hub preset as "Dashboard", suitable for "Kerncijfers" (key figures) (`terp-studio`,
   `scaffold.py`) — a promise the scaffolded `HubPage` can keep only as a line of text.

## The forks

### Fork 1 — where variety comes from

**A. Style variants per block.** Card's `variant` grows filled / tinted / elevated / flat, with
`tone` and `emphasis` on every block. The page author picks per block.

**B. A presentation vocabulary keyed on the shape of the data.** The author declares what a block
*is* — one figure, a figure against a target, facts about a record, values over time, a ranking, a
share, a status history, a collection — and the framework owns how each looks. Variety comes from
mixing shapes.

**C. B, plus a page frame that orders and rations.** A summary band (one per page, because it is a
slot), asymmetric compositions, and a single headline figure (checked). The collection is the
brightest object by rule, not by choice.

**Recommendation: C.**

- A is a second way to do an already-supported thing, for every block, with no failure it can
  observe. And it would not produce what the goal asks for: contrast is a *ranking* — one thing
  louder than the rest — and a per-block menu has no notion of rank. An agent given four looks for
  one box varies them page by page, which reads as noise.
- B turns the author's choice into a question about the data, which an agent can answer from the
  model it has just written. It is the BI tools' own mechanism, and the one that survives being
  driven by an agent.
- C adds the two things B cannot guarantee alone: an order (the summary first, the collection
  brightest) and scarcity (one band, one headline). Scarcity is what lets an accent mean something,
  and unlike variety it is decidable, so it can be gated.

*What would change it:* an app with a presentation need the vocabulary cannot express, for a reason
of its domain rather than taste. That reopens A for that case alone.

### Fork 2 — how asymmetric layout is written

**A. `span` on grid children** — a closed set (1 | 2 | full), carried by a child component or a
prop on every block.

**B. Named track templates on `Grid`** — a closed set such as `"2:1"`, `"1:2"`, `"3:1"`, `"1:1:1"`,
each defining its tracks and how it collapses at the one breakpoint. Anything finer is nesting: a
`Stack` in the narrow track holds two figures beside a chart.

**C. Free placement** — the BI canvas.

**Recommendation: B.**

- It is a closed set on the parent, so it needs neither the child component `layout.tsx` names as
  the reason `span` was refused, nor a second breakpoint (ADR 0097 §3).
- Rows cannot go ragged. With spans, `2 + 2` in three columns leaves a hole no lint can see, because
  it depends on how many children render.
- Every template collapses by construction, so the composition that replaces a fixed `columns={4}`
  row cannot clip on a phone.
- In the Studio's layout editor (design-system track phase 7) it is a picker, not a canvas.
- It meets ADR 0098's condition for `DashboardPage` — "the day spans do… a `Grid` decision" — with a
  `Grid` decision.
- C has no responsive behaviour, separates reading order from visual order, and is geometry an agent
  would invent.

*What would change it:* a composition that needs a tile spanning rows, which nesting cannot express.

### Fork 3 — the surface ladder

The midpoint between canvas and surface, tried by hand on hub cards and the page band, is the
proposal here.

**A.** Two levels, as today; only wire `--color-bg-canvas`.

**B.** One new semantic token, `--color-bg-subtle`, the midpoint of canvas and surface with explicit
per-theme values (ADR 0093), and one role per level:

| Level | Token | midday | twilight | evening | night | contrast | Read by |
|---|---|---|---|---|---|---|---|
| The page | `--color-bg-canvas` (now read) | `#eef1f6` | `#312c3f` | `#0f172a` | `#010409` | `#ffffff` | body, AppShell, the login view |
| Containers and chrome | `--color-bg-subtle` (new) | `#f7f8fb` | `#363044` | `#172033` | `#070b10` | `#ffffff` | page band, sequence bar, boxed Card, HubCard, profile card |
| Where data is read | `--color-bg-surface` | `#ffffff` | `#3a3449` | `#1e293b` | `#0d1117` | `#ffffff` | DataView frame (raised to `--shadow-md`), charts, stat tiles |
| The one headline | `--color-brand-primary` | | | | | | the headline figure |

**C.** Darken the canvas a step instead.

**Recommendation: B**, with its measured cost stated. In the midday theme the midpoint halves the
existing step, to 1.07:1 on each side, so a container's 1px border does the separating — the same
reasoning ADR 0098 §6 applied to the sidebar's edge, where a decorative separator beside a surface
that already differs in background is not a gated pairing. Text on `subtle` clears AA in every
theme (lowest: muted text in midday, 7.14:1). C is the fallback if the workbench shows the step too
faint, but it is the change the stylesheet's own record warns against — a table on a grey ground
reads as disabled — which B avoids, because tables stay on surface. The token ships in the same
commit as its readers (ADR 0094), and canvas comes off `UNREAD_TOKENS` with it.

### Fork 4 — charts, ahead of ADR 0158's trigger

ADR 0158 fixed how charts are drawn — SVG, styled only by attributes and tokens, a table
alternative, numbers through the `format` helpers, no dependency — and deferred every kind until two
observations name it.

**A. Hold the trigger.** Ship everything else; no chart until two reports.

**B. Amend the trigger, keep the contract.** The framework's own data counts as the observations —
the `sync` run aggregates and the `webhooks` delivery log (item 7 above) — together with the
dashboard the template will scaffold. Build the kinds 0158 already named — a line or area over
time, bars across categories, a sparkline for a stat — and, named here explicitly because 0158 did
not, three more that the same data asks for: columns as a mark of the over-time chart (per-period
counts), the status history (`SyncRun.status`, `WebhookDelivery.outcome`), and the proportion bar
(a `SyncRun`'s created, updated and failed counts as shares of the run).

**C. A chart library behind a Terp contract.**

**Recommendation: B**, recorded in the new ADR as an explicit amendment of 0158, not as a reading of
it. C is refused by 0158 itself and by ADR 0099 §3: a library's types would enter react-core's
public surface. A leaves the dashboard without its main visual and the run data without a picture.
Kinds 0158 did not name — donut, heatmap, small multiples, matrix — stay out until they bring
consumers of their own.

### Fork 5 — how "promote" is held

**A.** Guidance only: a `terp guide` topic and examples.

**B.** Structure: the archetypes carry the composition, and the template scaffolds a page that uses
it.

**C.** Gates on scarcity: one summary band (a slot) and at most one headline figure per page,
checked in both halves of the layout contract with the fix in the message.

**Recommendation: B and C, with A as the explanation.** Variety itself is not decidable from markup
— a page that is one table is often the right page — so a rule against monotony would have no
failure it could honestly observe, which ADR 0103 calls ceremony. Scarcity is decidable, so it is
gated. Variety is promoted by what the archetypes and the scaffold do by default, which is what an
agent copies.

## The vocabulary, by shape of data

Working names; the ADR settles them.

| The data | Presentation | New or existing | Consumer in the framework |
|---|---|---|---|
| One figure, with context | `Stat`: label, value, unit, a delta whose sentiment the caller declares, an optional sparkline | new | the scaffolded dashboard; `sync` run aggregates. HubCard's `stat` line renders through it, so a figure is shown one way |
| Several figures about one subject | `StatGroup`: a ruled row of stats, unframed in the summary band | new | the summary band on detail pages |
| A figure against a target | `Stat` with a target: the bands `Meter` already models (`low` / `high` / `optimum`) plus a target mark | a mode of `Stat`, reusing `Meter` | the scaffolded dashboard |
| A figure against the previous period | `Stat` with a comparison: the delta and a ghost series | a mode of `Stat` | the scaffolded dashboard |
| Facts about one record | `DetailList` with a ruled grid layout | a layout on an existing component | detail pages |
| Values over time | `TrendChart`: a line or area with an optional comparison series; columns for per-period counts | new (a 0158 kind) | `SyncRun` counts, `WebhookDelivery` attempts |
| Categories, ranked | `BarChart`: horizontal, the label inside the bar | new (a 0158 kind) | the scaffolded dashboard |
| A share of a whole | a stacked proportion bar with a worded legend | new | a `SyncRun`'s created / updated / failed counts |
| A status per run | `StatusHistory`: one cell per run, also as a DataView cell | new | `SyncRun.status`, `WebhookDelivery.outcome` |
| Events in order | `Timeline` | new | a record's audit trail on a detail page |
| Checks with a state | `StatusList` | new | to be named in phase 5, or not built |
| A collection | `DataView` gains panel chrome — title with count, filters with counts, a footer link — and cell presentations: status dot, inline bar, status history | modes on an existing component | every overview; `AuditLogAdmin` |
| Something needs action | `Alert` gains actions and a prominent size | a mode on an existing component | — |

A `Stat`'s sentiment is the caller's fact, for the reason ADR 0097 §5 gave when it refused a
navigation badge: whether a number is good or bad "is domain knowledge the shell does not have and
cannot infer". More rows is good news, more rejections is bad, and only the caller knows which.

**Refused or deferred:** a board (drag-and-drop and an ordering model are a capability, not a
presentation); a calendar heatmap, donut, small multiples and matrix (no consumer yet — and a bar
chart or proportion bar says what a donut says, more legibly); a page filter bar shared by every
visual (one filter state per page is a capability that deserves its own ADR); a stepper (no
consumer found); per-block style variants (fork 1A); free placement (fork 2C).

## The page frame

**The summary band.** A `Page` slot named `summary` — not "lead", which ADR 0135 already gives to
the `description` line — rendered full-bleed directly under the page band. It admits `Stat`,
`StatGroup`, `StatusHistory`, `Badge` and `Text`, and nothing else, and it is one per page because
it is a slot. It is not ADR 0123's hero band, which was refused as a marketing component with no
consumer in the framework: this one carries the page's own figures and names its consumers. Its
fill is a theme decision — the brand's soft tint by default, the surface, or the brand with its
contrast ink — as the shell's other bands are.

**Compositions.** `Grid` gains `template` (fork 2). `DashboardPage` ships as an archetype whose body
admits templated `Grid`s, the stat and chart families, `DataView`, `Alert` and `Card`, and whose
summary slot holds the headline figures. It answers "how is the whole doing", where the overview
ADR 0159 sanctions answers "how is each one doing", so it is not two names for one grid.

**One headline.** At most one `Stat` per page carries `headline` — the filled, accent-coloured
figure. Checked at runtime by the `Page` frame (the seam `verifySlotChildren` already uses) and by
the layout-contract lint, with the fix in the message: mark one figure as the headline and render
the others as ordinary stats.

**Roles decide treatment, not regions.** A stat tile, a chart and a DataView frame sit on surface
because data is read there; a boxed Card is a container on `subtle`; a plain Card is a heading on
the canvas. Nothing changes its look because of where it is placed — that would be styling an
author cannot predict from what they wrote.

## Theming, CSP and accessibility

- **One theme styles everything.** Every new rule reads tokens, and nothing is themed per page.
  "Bolder" or "calmer" is an app's `theme.css` and, through the token manifest, the Studio's
  styling editor: the summary band's fill, the chart palette, `subtle`.
- **Charts are SVG geometry** — `x`, `y`, `width`, `height`, `points` — coloured by sheet rules keyed
  on `data-*` attributes. That keeps `INLINE_STYLE_SITES` exact, keeps the template's production
  `style-src 'self'` intact (ADR 0104; `template/project/frontend/nginx.conf`), and matches 0158 to
  the letter. The study's prototype set bar heights with inline custom properties; that was a
  shortcut of the study, not part of the proposal.
- **Every chart ships a table alternative**, numbers go through the `format` helpers, and a tone is
  always also a word — a legend entry or a status label.
- **Contrast is gated.** New pairings go into `token-pairs.json`: chart marks at 3:1 against
  surface, text at AA on `subtle` and on the summary band's fills. Against today's token values
  every one already clears in every registered theme; the tightest cases:

| Pairing | Lowest across the themes |
|---|---|
| `--color-chart-1..5` against surface (3:1) | 3.19 — chart-3, midday |
| status success / warning / danger against surface (3:1 as a mark, 4.5:1 as a word) | 5.02 — midday |
| muted text on `subtle` (4.5:1) | 7.14 — midday |
| muted text on the brand's soft tint (4.5:1) | 5.19 — night |
| contrast ink on the brand fill (4.5:1) | 5.17 — midday |

## What every phase touches

A new component ships with a co-located test, its markers in `MARKERS` (`markers.test.ts`), rules in
`styles.ts`, default copy in `uiText` and the locale catalogs (with any new text prop added to the
i18n lint's `UI_TEXT_PROPERTIES`), a README row, workbench specimens with **linux and win32**
baselines, token pairs for any new colour, and a CHANGELOG entry. A slot change edits both halves of
the layout contract — `layoutContract.ts` and `eslint-boundaries/src/layouts.js` — and the pinned
marker set in `layoutContract.test.tsx`. A new archetype is exported by name and named in every
archetype list `test_layout_archetypes.py` reads (`template/project/AGENTS.md.jinja`,
`template/AGENTS.md`, the react-core README). terp-spec needs no change unless the layout
declaration gains a key: the spec lists no slots.

Two constraints on the work itself:

- **Baselines are recorded on both platforms, by two different routes.** linux in the pinned
  `mcr.microsoft.com/playwright:v1.63.0-noble` container from a `git archive` of the change, as the
  workbench README prescribes, and win32 natively. The screenshot spec says the browser is blocked
  by group policy on the machine its linux-only set was authored on; on the workstation phase 1
  was built on it is not, and phase 1 recorded its win32 baselines there (see below).
- **The Studio pins framework 0.27.0**, so none of this reaches its styling editor or its previews
  until the pin moves.

## Sequence

Every phase ends at a shippable point; nothing is half-wired between them.

- [x] **0 — Decide.** Every fork and open point went the recommended way, recorded as ADR 0169,
      with ADR 0158's trigger amended in place.
- [x] **1 — The surface ladder.** Wire `--color-bg-canvas`; add `--color-bg-subtle` with its readers
      (page band, boxed Card, HubCard); raise the DataView frame. Pairings, completeness and
      baselines re-recorded deliberately — every app's look moves here, so the release says so.
      **Built on top of #135–#139, merged together and awaiting their push to `main`:** canvas
      read by the body, the AppShell and the login view; `subtle` in every theme — midday
      `#f7f8fb`, twilight `#363044` (recomputed for #138's new twilight), evening `#172033`,
      night `#070b10`, contrast `#ffffff` — with seven text pairings, read by the boxed Card,
      the HubCard body, the profile card, the page band and #139's sequence bar, which carries
      the band's fill by design; the full DataView frame raised to `--shadow-md`; and `terp
      guide theming` saying the three backgrounds move as a set. Four gates mutation-checked,
      on the first build and again on this one. The release note is written, in the unreleased
      0.31.0 section's Changed entries and the upgrade notes on moving the backgrounds as a set.
- [x] **2 — Composition and figures.** `Grid` `template`; the `summary` slot; `Stat` and `StatGroup`
      with delta, sentiment and the sparkline (0158's first named kind); the one-headline check;
      both halves of the contract widened. **Built**, on top of phase 1. What the commit decided:
      - **Templates:** `"2:1"`, `"1:2"`, `"3:1"` and the equal `"1:1"`, `"1:1:1"`, `"1:1:1:1"` —
        the record's set, without a `"1:3"` it did not name. Every template collapses at the one
        cutover by a viewport query (one track; the four-track set to two). The types make
        `template` and `columns` exclusive.
      - **The summary band** is a second `<header data-terp="page-summary">`, so the body check
        drops it by tag as it drops the title band; its fill is a new token,
        `--color-bg-summary`, at each palette's brand soft tint, so the theme decides it
        without moving the tint other components share. Three text pairings declared on it.
        It follows the body: absent while the page loads or fails.
      - **The frame's two rules hold on every page under a contract, the plain `Page`
        included** — its body stays free, its frame does not. The contract data gained
        `summary` and `headline` tables beside `slots`; both message builders are
        parity-tested. The lint takes the larger branch of a conditional and stops at a nested
        page.
      - **`Stat`** is phrasing content throughout (a `<span>` root), so it is valid inside a
        `HubCard`'s link; that is also why the sparkline's data alternative is text (each
        point's label and value, listed in the app's locale) rather than a table. The delta is
        a pill on its sentiment's soft fill — success ink on the summary tint measures 4.26 in
        midday, under AA, and on its own soft fill it is the success badge's declared pairing
        everywhere. The sentiment is also a word in the accessibility tree ("favourable" /
        "unfavourable"); the sign is printed, so the arrow is decorative. `target` reuses
        `Meter`; the ghost series of a comparison period waits for a consumer, the delta's
        `label` carrying the period meanwhile.
      - **`StatGroup`** is always unframed; its rules are drawn into the column gap and clipped
        at a line's start by the group's own overflow.
      - **The delta's period is `label`,** because the i18n lint reads object keys by name
        anywhere in app code, and a `period` key would have flagged every `{ period: "month" }`
        an app sends to its API.
      - The admin hub's totals render through `Stat`, which is the framework consumer ADR
        0169 §5 names for "HubCard's `stat` rendered through it".
      Twenty-two gates mutation-checked; ten specimens with baselines on both platforms; axe
      clean on them in all five themes; three computed-lane measurements (template tracks, the
      band's flush bleed, the group's clipped rules).
- [x] **3 — The prominent collection.** DataView panel chrome and cell presentations;
      `DetailList`'s grid layout; `Alert` actions. **Built**, on top of phase 2, each piece with
      a framework consumer in the same commit (ADR 0099):
      - **`DataView` `title`**, an `<h3>` with the count beside it once the repository has
        said one, printed in the app's locale and part of the heading's name. Consumer: the
        packaged group screen, whose members and permissions were an `h2` over an embedded
        view — they are titled collections now, with the add forms in their toolbars.
      - **Cell presentations on the column:** `status` (a dot of the row's tone before the
        cell's word; no word, no dot) and `bar` (the number as a `Meter` against the largest
        value shown, or a declared `max`). One renderer serves the table and the cards.
        Consumers: the users overview's status, the groups overview's sizes. Four non-text
        pairings declared for the toned dots; the neutral dot is the subtle ink, already held
        by a text pairing.
      - **`DetailList` `layout="grid"`**, the ruled grid, its rules drawn by the cells and
        clipped at the list's edge as `StatGroup`'s are; `columns="auto"` by default. It
        landed with no framework consumer, though the commit said each piece had one; the
        review below caught it, and the packaged user and group screens take it since.
      - **`Alert` `actions`.** Consumer: the module-access panel's revoke for a retired
        module's rung, which was a button row beside the alert.
      **Deferred, each to its consumer:** the footer link goes with the scaffolded dashboard
      (phase 6), which is what shows a few rows and links to all of them; filters with counts
      wait for a consumer that has the counts — a count per filter value is a backend
      capability, and no framework endpoint returns one; `Alert`'s prominent size has no
      consumer. The count guard DataView first carried for an error was dropped once measured:
      the query hook already forgets the total on a failed query, and the test that holds
      that now loads a page before failing one.
- [x] **4 — Charts under the amended 0158.** `TrendChart` (line, area, columns), `BarChart`, the
      proportion bar, `StatusHistory`; table alternatives; chart pairings gated, which takes the
      chart tokens off `UNREAD_TOKENS`. **Built**, on top of the first release's three phases.
      What the commit settled:
      - **The axis has three round ticks in two equal steps,** so its labels stand on their
        gridlines through `space-between` with no position of their own — measured in the
        browser, as is a column chart's labels standing under their columns. A line's axis starts
        where its data does; an area's and columns' keep zero.
      - **`BarChart` is its own table** — row headers, printed values, the bar a cell for the eye —
        where `TrendChart` carries a visually hidden one; `ProportionBar`'s legend is its data
        (name, count, share); `StatusHistory` prints its latest ending and reads every run out.
      - **A run's ending is an outcome object** (`{ label, tone }`), not a `status` string: the
        i18n lint reads every public text property as a key it checks anywhere in app code, and
        a `status` key would have flagged every `{ status: "paused" }` an app writes.
      - **The summary band admits `StatusHistory`** in both halves of the contract, as ADR 0169
        §4 says; a `DataView` column takes `history`.
      - The chart ramp is declared at 3:1 against the surface and the status cells against the
        summary band; the five chart tokens came off `UNREAD_TOKENS`.
      **Framework consumer:** this commit named the scaffolded dashboard of phase 6. That was
      wrong: phase 6 found that a new app has no data over time, and its dashboard draws figures,
      not charts (ADR 0169's second amendment). The charts stand on ADR 0169 §6's other
      observation, the framework's own `SyncRun` and `WebhookDelivery` data, which no packaged
      screen draws yet; the workbench's dashboard specimens are the composition such a screen
      takes. Which screen comes first is open (below).
- [x] **5 — Time and state.** `Timeline` for a record's audit trail; `StatusList` only if this
      phase names its consumer. **Built.** `Timeline` is an ordered list of events, each its
      words, a `<time>` with its instant, an optional detail and a toned marker. Its consumer
      needed one backend change: the audit list takes `target_type` and `target_id` (both columns
      were already indexed), bounded at 128 like the columns, and the packaged user and group
      screens show their record's own history, newest first, quietly absent when the trail is
      unreadable or empty. The four audit actions have words in both catalogs, which the audit
      log's action column uses too. **`StatusList` is not built:** no phase named a consumer for
      a check list, and the rule this phase was given was to build it only with one.
- [x] **6 — The archetype and the guidance.** `DashboardPage`; the scaffold's hub preset becomes a
      dashboard that keeps the Studio wizard's "Kerncijfers" promise; `terp guide layouts`
      rewritten around the vocabulary — a data-shape table an agent can follow — and its stale
      archetype lists fixed (below); the Studio's pin moved. **Started early, because the
      first release's guidance depends on it:** the guide's two stale archetype lists are
      complete (`terp guide frontend` named four, `terp guide layouts` three, and the latter
      now gives FormPage, SettingsPage and SplitPage their slot rows), and
      `test_layout_archetypes.py` reads every `terp guide` topic as well as the three files —
      mutation-checked: the old four-name sentence fails it. The data-shape table and the frame
      rules are in `terp guide layouts` and both `AGENTS.md` files since phase 2.
      **Built.** `DashboardPage` is the eighth archetype, its slot in both halves of the
      contract; its body admits a little more than ADR 0169 §4 lists, recorded in the ADR's
      second amendment. The hub preset renders one: three key figures in the summary band —
      the dash, and a line saying they arrive with the first area's data — and the area cards in
      a `"1:1:1"` section; the process, portal and blank landings render byte for byte as before.
      End to end, the rendered hub app installed this branch's packed packages and wheels and
      passed its own gates (routes, typecheck, lint, build, its Python suite, ruff and deptry);
      in a browser its summary band, figures and three tracks rendered with no refusal, one
      track on a phone, in `midday` and `night`, and the packaged user and group screens showed
      their record's history from the branch's backend. The workbench's dashboard specimens
      render `DashboardPage` and still match their baselines, which is the archetype adding a
      slot and nothing else. **Not done:** the Studio's pin, which waits for a release; and
      the DataView footer link phase 3 deferred to this phase, because the scaffolded dashboard
      has no collection to link from until a module exists.

Releases: phases 1–3 together, as the design-system track shipped 0.10.0, so consumers cross the
styling change once; 4–6 after.

## What the review of phases 2 and 3 found

An independent review of the two phases, read against this draft and the ADRs, found these,
each fixed in one follow-up with a test that fails without the fix:

- A percent `bar` printed the share of the largest value, not the rate (a `Meter` prints a
  percentage as the share of its range). Percent bars are drawn against 100%, and a `max`
  beside a percent format is refused.
- The sparkline's text ran together in English ("Week 1 12 Week 2 15"): the narrow unit list
  joins with spaces. It is a conjunction list of "label: value" now.
- The runtime counted headlines in the DOM once, after the page rendered: a figure that rendered
  later was never counted, and a nested page's figures were counted twice. Headlines register
  with their page now. The lint, for its part, reported `summary={null}` as text and counted
  expression-valued `headline`s; it treats both as the runtime does.
- Subtle text on the night summary band measured 4.26. Night's band is a step darker (subtle
  4.68) and `subtle-on-summary` is declared; the status dots are declared on the canvas and on
  a container as well as on the surface.
- The ruled layouts clipped a focus ring's side at the text's edge. Their cells are padded half
  a gap and the groups reach out by it, so the clip sits outside the ring.
- A delta that rounds to zero showed an up arrow and "favourable" beside "0%"; the direction
  follows the printed change now, and the sign survives a caller's `signDisplay`.
- The group screen nested its two collections under the access panel's h2 in the outline; the
  panel's title is an h3, the level of every section on a page.
- The claims: the ruled grid had no framework consumer, the summary band's token does not
  follow a rebrand of the soft tint (the theming guide and the upgrade note say so now), and the
  sparkline's text alternative departed from ADR 0158's table without a record (ADR 0169's
  amendment is that record). Phase 2's figure family, band and templates name the scaffolded
  dashboard of phase 6 as their framework consumer; until it lands the admin hub's totals are
  the one consumer in the framework.

## What the end-to-end pass found

After phase 6, the scaffolded hub app and an existing app were run on this branch in a browser,
and the briefing an app's agent reads was read the way that agent reads it:

- **The briefing named no dashboard body and said nothing about alternation.** The generated
  `AGENTS.md` listed the hub, overview and detail bodies only, and still called `Grid` a
  detail-body component, while the app it describes now lands on a dashboard; and nothing told
  an agent that a page of boxed cards is the monotony ADR 0169 exists to end. The app's
  `AGENTS.md`, `terp guide layouts`, the template's own `AGENTS.md` and the react-core README
  now say how to pick the archetype by the question a page answers and how to alternate
  framed and unframed blocks — the frame for the data a reader works with, a boxed `Card` for
  a group of controls or a record's section, and the figures, facts, events and prose on the
  page. The existing app's overview, rebuilt on exactly that guidance, read as one designed
  page where it had read as four boxes.
- **A headline in a group of figures poked past the content edge.** The review's focus-ring
  fix let the group reach out by half a gap, and a filled headline reached out with it: 12px
  past the edge every other block keeps, 4px from the screen's edge on a phone. It is held off
  its neighbours on both sides now, with no rule beside it, measured in the computed lane at
  the desk width and on a phone (three mutations, all red), and the workbench shows the case
  it had no specimen for.
- **A platform error showed in English on a Dutch screen.** Capturing every screen back to back
  tripped the rate limiter, and its sentence arrived as written under the framework's Dutch
  "Er is iets misgegaan.". The UI words a failure by its code, and none of the middleware's
  codes nor `internal_error` had wording. A gate written for the three seen found six more, and
  the review below found that it read one file of the core's error classes; it reads the whole
  core now.

## What a design pass over the example app found

Read as a designer reads screens, the example app's redesign still had faults the framework
owned, each fixed with a measurement in the computed lane and mutation-checked:

- **A row of figures did not share a line.** The summary band centred its items, so a headline
  tile with a sparkline set the group beside it 20px lower; inside a row, only the headline had
  block padding, so its label sat 12px under the rest. The band hangs its items from the top,
  and every cell takes the headline's block padding.
- **A lone figure in a boxed card was a tile inside a box.** The card is its frame now, as a hub
  card's is; a plain card has no frame to lend, so there the figure keeps its tile.
- **A bar column took some 13rem whatever it was declared**, because the meter's 10rem measure
  is what an automatic table layout cannot shrink, and the names beside it wrapped. In a table
  cell the measure is 6rem, one for the whole column, so its bars still compare.
- **An identifier in a table cell broke at its hyphen** into two chips on two lines; it stays
  whole, and its column widens to it.

The same pass changed the example app itself: the collection names and counts itself, notes are
notes, the limits are a plain list, a search's counts are its figures in the band, and the
basis tab's verdicts are status dots. And it raised one question for the owner: the page band
makes every line a control tall (#138), which sets a lead line 43px under a small title.

## What the review of phases 4 to 6 found

An independent review of everything after phase 3, read against ADR 0169 and this draft, found
these. Each is fixed with a test or a measurement that fails without the fix, and every one of
those was mutation-checked.

- **A comparison series was scaled to itself.** "This month so far" against last month drew the
  shorter month stretched to the full width, and the table paired them by index and dropped
  the longer one's rest. Both series stand on one index scale now, the table lists the longer
  one whole, and over columns the comparison bends at the columns' centres and is drawn above
  them, where behind them it was hidden.
- **A line's middle label stood between two points** whenever the count was even: the labels sit
  at the plot's ends and centre, and only an odd count has a point at the centre. The middle
  label is printed for an odd count only, measured in the computed lane.
- **A point with no neighbour drew nothing** — a series of one point, or a value between two
  gaps — because a polyline of one point is never stroked. It is a dot.
- **Printed column labels were cut to their band** on a narrow tile, and **a bar chart's long
  names never ellipsised**, because a table cell's max-inline-size is ignored in an automatic
  table layout. Labels overflow their band centred, and a name stops at a third of the chart in
  container units; both are measured at a phone's width on specimens of their own.
- **An axis of counts could step by 2.5**, printing "2.5" for a number of runs, or "3" under a
  format that rounds. An axis whose values are whole numbers steps in whole numbers.
- **The error-code gate read one file of the core's error classes**, and claimed every code the
  platform emits. It reads every module of the core, checks that it read every envelope call,
  and keeps the one code that keeps its detail on purpose — a weak password's, which names the
  policy's numbers — in a list with its reason. The packaged admin screens printed the
  backend's detail in their notices whatever the code; they word it now.
- **Two tests could not fail.** The audit filter's test passed with the record type ignored,
  over a trail of users only; a group's event is in it now. The router's refusal of an
  unframed view passed before the view had even mounted; it waits for the view, then for the
  refusal, and checks that the refusal names every archetype — which it now reads from the
  contract, where it had named four.
- **The descriptions disagreed with the contract.** The dashboard's body was described as
  "exactly" a shorter list than the one the contract admits, "templated" as a rule the
  contract does not check, and the run history as a chart the body refused. The body admits
  the run history now, and the README, the changelog and the ADR say what the contract does;
  the guide no longer calls every landing into the areas a hub when the hub preset is a
  dashboard. The repository's own briefing named four archetypes, and the archetype gate reads
  it now.
- **Accessibility:** the timeline states its list role, which WebKit drops once the markers are
  gone; the trend chart's table is named by the caption instead of repeating it; the bar
  chart's table is named, and its bar cell hidden rather than read as blank; and a proportion's
  name and count are no longer read as one word.
- A run history with no runs rendered half a sentence; it renders nothing. The list joins
  behind a figure's and a history's text alternative are kept, like the other formatters.

## What the contrast pass settled (ADR 0170)

Asked before the release whether the palettes' contrast is right for maximum readability, the
measurement said: in midday, nearly; in the three darks, no. WCAG 2's ratio passed every declared
pairing while APCA put the darks' secondary text, links and badges as low as Lc 41, and the
control outline failed SC 1.4.11 in four palettes. The owner chose the maximum level, and it
shipped as ADR 0170:

- [x] Every text pairing declares its `reading` and is held to APCA (body Lc 90, secondary 75,
      incidental 60) beside WCAG; the manifest publishes the floors with the APCA build.
- [x] The darks' muted, subtle, accent, status and sidebar-muted inks lifted by the least change
      that reaches each floor; night's main text eased from Lc 101 to 95.
- [x] The lead line, a field's hint and a tile's description moved from the subtle ink to the
      muted one; `Text`'s `subtle` tone documented as the incidental reading.
- [x] The control outline moved onto `--color-border-strong` at 3:1, and `BELOW_UI` removed.
      Darkening `neutral-300` was tried first and broke the ramp (300 past 400, a hovered
      field's border lighter than its resting one), which is why a ramp-order gate came with it.
- [x] The danger button filled from tokens of its own, a deep red with a white label: its old
      dark-palette label read at Lc 44 to 57, and the lifted ink made it pale pink.

## Open after phase 6

- [x] **Which screen draws the charts first: the admin hub, as a dashboard** (the owner's
  call), built for 0.32.0 as ADR 0171. The proposal put three rendered directions and two data
  decisions forward and the owner took all three recommendations: the areas right under the
  figures, the trail counted by the viewer's own calendar days, and active accounts as a total
  under a status filter. Packaged screens for sync runs and webhook deliveries stay the later
  candidate.
- **The capabilities' error codes.** The core's are worded; the capabilities' own — files,
  multi-factor sign-in, users, auth, access, single sign-on, egress, mail, tenancy and webhooks
  — still reach a screen as the backend's English detail. Several carry specifics a fixed
  wording would drop, so each wants its own decision, and some want the envelope to carry
  their numbers.
- **The release: one, as 0.31.0** (the owner's call), with the design pass, the band's
  subtitle and the contrast pass in it. The Studio's framework pin moves after it.

## Found along the way

Recorded so they are not lost; this proposal does not fix them on its own.

- `terp guide frontend` names four archetypes ("Page / OverviewPage / DetailPage / HubPage") and
  `terp guide layouts` covers only Hub, Overview and Detail. FormPage, SettingsPage and SplitPage are
  missing from both. It is the staleness `test_layout_archetypes.py` was written to catch, but that
  gate reads the two `AGENTS.md` files and the react-core README, not the guide topics, and
  `test_cli_guide.py` checks neither list. Phase 6 fixes the text, and should extend the gate to the
  guide in the same change.
- A fixed `columns={4}` row that clips at phone width is not a bug under ADR 0097 §3, but it is a
  legal configuration that renders broken. Templates remove the reason to write it; whether fixed
  counts should collapse too is a question for the ADR.
- ~~A control on a boxed card sits on `--color-bg-subtle`, between the two control-boundary
  floors `BELOW_UI` recorded.~~ Fixed by ADR 0170: the outline is `--color-border-strong`, solved
  at 3:1 against the subtle rung as well as the canvas, the surface and a raised panel.
- `sidebar-text-on-accent` and `sidebar-nav-link-hover` in `token-pairs.json` name the same two
  tokens, so one pairing is measured twice under two ids. Harmless to the gate, but it overstates
  the coverage by one pairing, which the non-text section refuses for its own entries. Not
  acted on here.
- `visual/specimens.spec.ts` says win32 baselines cannot be recorded "on the machine these were
  authored on" because group policy blocks the browser. On the workstation phase 1 was built on,
  sixteen untouched specimens matched their win32 baselines pixel for pixel and the lane recorded
  the changed ones, so the `LINUX_ONLY` set may now be recordable there. Not acted on here.
- The layout contract's opt-out, a `// terp-allow-layout-contract` marker, silences only the
  lint. The runtime half, which ADR 0079 calls authoritative, has no way to read it and refuses
  the same view, so a justified marker passes the build and fails the page. It predates this
  work and holds for the summary and headline rules exactly as for the body slots; it is a
  question for ADR 0079, not acted on here.
- **Timestamps read from SQLite display as UTC wall time.** A timezone-aware column round-trips
  naive on SQLite (the identity capability says so where it compares an expiry), so the API
  serialises such a timestamp without an offset, and the browser reads a string without an
  offset as local time. In the scaffolded app at UTC+2, an event recorded at 17:12 local showed
  as 15:12 in the audit log, a record's history and its "Created" field alike. PostgreSQL
  returns aware values and is not affected. It predates this work; the fix belongs in how the
  API serialises a timestamp, not in the frontend, where a naive string can also be a
  `datetime-local` input's local time.
- `test_spec_catalog.py::test_frontend_catalog_covers_every_named_plugin_rule` fails on that
  workstation with or without this branch — the local terp-spec candidate lacks
  `no-framework-markers` (ADR 0160) — so it is an environment fact, not a regression.

## What would change this

- The midpoint reads too faint in the workbench → fork 3C.
- A domain need the vocabulary cannot express → fork 1A, for that case.
- A composition nesting cannot express → fork 2A.
- A ruling that the owner's direction does not count as evidence → fork 4A.

## Open for the decision

1. Forks 1–5. The recommendations are C, B, B, B, and B with C.
2. `DashboardPage` as a new archetype (recommended), or a wider `OverviewPage` slot table.
3. The summary band's default fill: the brand's soft tint (recommended), the surface, or the brand.
4. ~~The release grouping above.~~ One release, 0.31.0.
