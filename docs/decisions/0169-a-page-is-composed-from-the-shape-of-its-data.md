# 0169 — A page is composed from the shape of its data, and its emphasis is rationed

- **Status:** Accepted (2026-10-03); being implemented in phases, sequenced and tracked in
  [presentation-and-composition-design.md](../internal/drafts/presentation-and-composition-design.md).
  Amends [ADR 0158](0158-a-quantity-is-shown-one-way.md)'s trigger for building charts — its
  contract stands (§6).
- **Date:** 2026-10-03
- **Relates:** [ADR 0158](0158-a-quantity-is-shown-one-way.md) (the chart contract kept, the
  trigger amended), [ADR 0098](0098-archetypes-measures-and-the-density-island.md) (the
  condition under which `DashboardPage` earns its place, met by §2),
  [ADR 0099](0099-the-component-gap-and-what-is-not-in-it.md) (every component names its
  consumer), [ADR 0093](0093-semantic-token-layer-and-named-themes.md) and
  [ADR 0094](0094-attribute-keyed-styling.md) (how a token is admitted and read),
  [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (one breakpoint; the inline-style
  ledger), [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot tables this widens),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) and
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (what kind of rule
  this is), [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md) (the hero band
  the summary band is not), [ADR 0135](0135-the-page-band-spends-a-second-row-only-when-one-is-earned.md)
  (the "lead line" name already taken)

---

## Context

A Terp page is one object repeated. Card and every other in-flow block are a `--color-bg-surface`
fill in a hairline frame on the canvas; a figure renders as a Card title over smaller text, so the
label is louder than the number; `Grid` gives every block the same weight; the chart palette is
published and read by nothing; and `terp guide layouts` steers an agent away from any other
composition. Meanwhile the framework already shapes data it cannot draw — the `sync` capability
stores each `SyncRun`'s aggregates for a stats view, `webhooks` keeps an outcome per delivery
attempt — and the Studio sells the hub preset as a dashboard of key figures.

The platform's owner set the direction: the framework should promote contrast and variety in
layout and styling — framed and unframed content together, new ways to present key values and
KPIs, as BI dashboards and current product interfaces do — while one theme and consistent styling
keep governing every app. The proposal put five forks, each with a recommendation; the owner
chose the recommendations. The forks, the options not taken, the measurements behind them and the
sequence are in the draft linked above; this record keeps the decisions.

In ADR 0111's terms this constrains a **usage pattern** and no capability: every page an app can
build today stays buildable.

## Decision

### 1. Variety comes from the shape of the data; the page frame rations emphasis

A page author declares what a block *is* — one figure, a figure against a target or a period,
facts about a record, values over time, a ranking, a share of a whole, a status per run, events in
order, a collection — and the framework owns how each one looks. There are no style variants per
block: no filled, tinted or elevated Card, and no `tone` or `emphasis` prop on blocks in general.
Contrast is a ranking, and a per-block menu has no notion of rank.

### 2. Asymmetric layout is a closed set of track templates on `Grid`

`Grid` gains `template`, a closed set of named track templates (`"2:1"`, `"1:2"`, `"3:1"` and the
equal sets), each defining its tracks and how it collapses at the one breakpoint. Anything finer
is nesting. There is no `span` and no free placement. This is the `Grid` decision ADR 0098 named
as the condition for `DashboardPage`.

### 3. The surface ladder has four rungs, and each has a role

| Rung | Token | Read by |
|---|---|---|
| The page | `--color-bg-canvas` — read for the first time | `body`, AppShell, the login view |
| Containers and chrome | `--color-bg-subtle` — new: the midpoint of canvas and surface, with explicit per-theme values | the page band and the sequence bar, a boxed Card, the HubCard body, the profile card |
| Where data is read | `--color-bg-surface` | the DataView frame, raised to `--shadow-md`; and charts and stat tiles as they land |
| The one headline | `--color-brand-primary` with its contrast ink | the headline figure (§4) |

Roles decide treatment, never placement: nothing changes its look because of where it sits.

### 4. The page frame: a summary band, a dashboard archetype, one headline

- **`summary`** is a `Page` slot rendered full-bleed under the page band. It admits the figure
  family, the status history, `Badge` and `Text`. It is one per page because it is a slot. Its
  fill is a theme decision; the default is the brand's soft tint. It is not ADR 0123's hero band:
  it carries the page's own figures and names its consumers. It is not called "lead", which ADR
  0135 gives to the `description` line.
- **`DashboardPage`** ships: its body admits templated `Grid`s, the figure and chart families,
  `DataView`, `Alert` and `Card`. It answers "how is the whole doing", where an overview answers
  "how is each one doing".
- **One headline per page.** At most one figure carries `headline`, the filled, accent-coloured
  one. Checked at runtime by the `Page` frame and at build time by the layout-contract lint, and
  the message carries the fix. It is a usage-pattern rule, held beside ADR 0059's boundary and ADR
  0079's slot contracts under ADR 0103, not a security invariant.

### 5. The vocabulary

Working names, fixed in the commit that lands each one, and each names its consumer then (ADR
0099): a figure (`Stat`) with a delta whose sentiment the caller declares, a sparkline, a target
drawn with `Meter`'s bands, a comparison period, and HubCard's `stat` rendered through it; a
group of figures; `DetailList` gains a ruled grid layout; an over-time chart (line, area,
columns); a bar chart across categories; a proportion bar; a status history, also as a DataView
cell; a timeline; DataView panel chrome (title with count, filters with counts, a footer link) and
cell presentations; `Alert` gains actions. A check list ships only if its phase names a consumer.

Sentiment is the caller's fact: whether a number is good or bad is domain knowledge the framework
does not have (the reason ADR 0097 §5 gave for refusing a navigation badge).

### 6. Charts: ADR 0158's contract stands, its trigger is amended

The contract is unchanged: SVG, styled only by attributes and tokens, a table alternative, numbers
through the `format` helpers, no dependency. The trigger — "built when two observations name it" —
is amended: the framework's own data counts as the observations (`SyncRun` aggregates and status,
`WebhookDelivery` outcomes), together with the dashboard the template scaffolds. The kinds built
are 0158's three — a line or area over time, bars across categories, a sparkline for a figure —
and three the same data asks for, named here because 0158 did not: columns as a mark of the
over-time chart, the status history, and the proportion bar. Any other kind waits for a consumer of
its own.

### 7. How everything is drawn and held

- Chart geometry is SVG attributes; colour comes from sheet rules keyed on `data-*` attributes.
  Nothing new is styled inline, so `INLINE_STYLE_SITES` does not move and the production
  `style-src 'self'` holds ([ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md)).
- A tone is always also a word.
- New colour pairings join `token-pairs.json`: chart marks at 3:1 against surface, text at AA on
  `--color-bg-subtle` and on the summary band's fills, in every registered theme.
- Variety itself is not gated: a page that is one table is often the right page, and a rule
  against monotony would have no failure it could honestly observe. It is promoted by what the
  archetypes and the scaffold do by default. `terp guide layouts` is rewritten around a table of
  data shapes, and the guide's archetype lists come under `test_layout_archetypes.py`.

### 8. Release

Phases 1–3 (the surface ladder, composition and figures, the prominent collection) ship together
in one release, so consumers cross the styling change once. Phases 4–6 follow.

## Consequences

- Every app's look moves when phase 1 lands: cards and the page band step back to
  `--color-bg-subtle`, and the collection becomes the brightest object on the page. The release
  says so.
- The Studio's styling editor gains the new tokens through the token manifest, and only once its
  framework pin moves past this release.
- In the midday theme the midpoint halves the existing step between canvas and surface, so a
  container's edge is carried by its border. If the workbench shows that too faint across the
  themes, the fallback the draft records is a darker canvas — the one change this record does not
  make.

## Amendment (2026-10-03): what building the first three phases settled

Three choices the phases made are decisions rather than details, and the first departs from
the letter of ADR 0158's contract, so they are recorded here.

- **A sparkline's alternative is its series as text, not a table.** ADR 0158 asks every chart
  for a table alternative, and §6 above keeps that contract. A figure (`Stat`) is phrasing
  content throughout, because a hub card's stat row is inside the card's link, and a table
  cannot sit there. So the sparkline is drawn for the eye and every point is read out, label and
  value, in the order drawn and joined as the app's locale joins a list — the one row a table of
  a sparkline would have, read as the sentence it is. The larger charts of phase 4 have no such
  constraint and keep the table.
- **One headline per page is counted by registration.** A figure marked headline registers with
  the nearest page when it mounts. A count of the page's DOM, taken when the page rendered,
  missed a figure that rendered after its own data arrived, and counted a nested page's figures
  as the outer page's, which the lint does not. The lint counts a page element's static JSX and
  only the headlines the file itself says yes to; an expression is left to the page's count.
- **A percent bar is drawn against 100%.** A `Meter` prints a percentage as the value's share of
  its range, so a column of rates scaled to its largest value printed shares; its rates' own
  range is 0 to 1, and a `max` beside a percent format is refused.

## Amendment (2026-10-03): what building phases 4 to 6 settled

- **The dashboard's body admits more than §4 lists.** Besides `Grid`s, the figure and chart
  families (the chart family with `StatusHistory`), `DataView`, `Alert` and `Card`, it admits
  `Stack` — §2 makes nesting the way to anything finer than a template, and `Stack` is what
  nests a column — `Timeline`, which §5 lists, `Divider` and `Text`, the framework's states, and
  `ConfirmDialog` for an alert's action, as every other archetype with a free body does. §4's
  "templated" is the guide's ask rather than the contract's: the slot admits any `Grid`, as the
  detail and form bodies do.
- **The scaffolded dashboard draws figures, not charts.** A new app has no data over time, so
  the hub preset's dashboard carries three key figures in its summary band, each the dash
  until a module gives it a value, and the area cards in a templated section. A chart there
  would be a drawing of nothing. So of §6's observations, the scaffold counts for the figure
  family and the templates, and the charts stand on the framework's own data alone, which no
  packaged screen draws yet: `SyncRun` and `WebhookDelivery` are not in the base profile the
  typed client covers. Which screen should draw them first is left open.
