# 0099 — The component gap, and the thirteen things that are not in it

- **Status:** Accepted
- **Date:** 2026-08-24
- **Relates:** [ADR 0094](0094-attribute-keyed-styling.md) (the attribute-versus-inline line every
  new marker and the column step land on), [ADR 0096](0096-typed-seams-cover-the-common-case.md)
  (§3's download seam and §4's refusal of a general dialog — the same test applied twice),
  [ADR 0097](0097-shell-parameters-and-ordered-navigation.md) (§4 names the command palette this
  ADR defers, and §5 is the refusal this one is modelled on),
  [ADR 0079](0079-slot-typed-layout-contracts.md) (the slot tables a new component would have to
  enter, and none of the refused ones would).

---

## Context

A list of eighteen candidate components was raised against `@terpjs/react-core`: form seams,
skeletons, progress, accordions, viewers, a second table. This ADR is what surveying them
produced.

**Thirteen are refused.** That is the product, not a side effect of it. A refusal that lives only
in someone's head gets re-proposed every few months, and each re-proposal costs the same survey
again — so the arguments are written down here, with the evidence that decided them, in a form a
future reader can disagree with on the merits rather than re-derive.

The test throughout is the one the framework has been applying since 0096 §4: **a component that
cannot name a consumer in this framework is declined.** "An app might want it" is not a consumer.
It is deliberately a high bar, and it cuts both ways — §1 builds two things precisely because the
consumers were already there, written twice.

## Decision

### 1. Six things ship, and two of them are subtractions

| Shipped | Consumer that existed before it |
|---|---|
| `format.ts` — locale-aware date/number helpers | Seven in-package sites formatting with no locale argument, five more in the example app |
| `ApiError.fields` | `Field.error`: a designed, styled, aria-wired prop with **zero** production consumers |
| `ColumnWidth` | Twenty-two declared column widths, none of which did anything |
| `Avatar` | The same initials tile, shipped **twice**, as two eleven-declaration rules |
| `Input type="password"` reveal | Four password fields, none revealable, and no app able to add one |
| `Code block` for the audit payload | A `<pre>` whose own comment cited `Code`'s rationale |

Two of those *remove* surface. `Avatar` merges two markers into one and `admin-payload` retires
entirely, so the marker inventory ends at **200**, one lower than it started, having gained two
names and lost three.

That is worth stating as a rule rather than an accident: **the third answer to "should we build
this" is "it exists twice, merge it."** The list of eighteen contained no such item, because a
duplicate does not look like a gap from the outside.

### 2. The thirteen refusals

Each of these was checked against the tree rather than reasoned about in the abstract.

**Skeleton.** A skeleton is worth its rules only when it mirrors a specific layout, and the one
surface with row geometry to mirror already ships its own (`DataView`'s `isLoading`). The reflow it
was proposed to fix does not exist: `HubCard` already reserves its stat row with a non-breaking
space.

**Progress.** Nothing in the framework can produce a percentage. `uploadFile` is a single POST
through the typed client, `fetch` reports no upload progress, and `FileUpload` is correspondingly a
boolean `busy`. Indeterminate waiting is already `Button loading` and `InlineSpinner`.

**Accordion.** An accordion is `Tabs` stacked vertically with "exactly one open" relaxed — same
item array, same roving focus, same panel wiring. That is a policy over a disclosure set, not a
second component, and there is no disclosure set to apply it to.

**Collapsible.** Nothing in the framework has anything to collapse. `NavItem` has no children, row
disclosure is `DataViewExpandableRow`, and the long detail screens use always-visible `Card`
sections. `<details>` / `<summary>` are not in `restrictedElements`, so no app is blocked today —
only unstyled, which is a treatment gap and not a component gap.

**ButtonGroup.** A cluster of buttons with no shared state is `Stack direction="row"`. The one
grouped control in the package is not a ButtonGroup at all: the DataView toolbar's layout switch is
a segmented single-select carrying `aria-pressed`, which is a `RadioGroup` in different clothes,
with one caller. Shipping the named thing would leave the real thing bespoke.

**A standalone Breadcrumb.** `Breadcrumbs` has been the standalone component since before `Page`
used it — its own props, its own `nav` / `ol` / `aria-current` markup, its own test file, its own
export. The list item described the wrapper, not the part.

**A standalone Pagination.** `DataViewPagination` is exported and already renders outside a
`DataView`, because `useDataViewText` carries a context default. The gap was a name, and the only
pageable collection in the framework is the one whose footer this already is.

**A table outside DataView.** `DataView variant="embedded"` *is* the plain table, and
`InMemoryDataViewRepository` needs two functions, `getRowId` and `getValue`. A second table would
be a second `<table>` surface that quietly drops sorting, resizing, column settings, the mobile
card reflow and row
activation — and it would contradict `restrictedElements.table`. What was missing was not a
component but the recipe, so the lint guidance now carries it (§4).

**A code viewer.** Refused twice now. `Code block` renders a bordered, scrollable,
keyboard-reachable `<pre>`. The second refusal is this phase's, and it went further: the audit
payload turned out to *be* one, written out again.

**A JSON viewer.** Same finding, folded rather than declined in the abstract: `JSON.stringify(x,
null, 2)` inside `<Code block>` is the whole feature, and adopting it took the marker count down.

**A diff viewer.** No consumer. `AuditEventRead` carries one redacted payload snapshot, not a
before/after pair, and nothing in the framework holds two versions of anything. Myers being ~100
zero-dependency lines is beside the point and is recorded here so nobody "fixes" the decline by
vendoring an algorithm: cheapness is not a consumer.

**A download primitive.** ADR 0096 §3 already shipped it — `saveBlob`, `downloadUrl`,
`fetchDownload`, `useEndpointDownload`, all exported, with tests.

**A `FieldArray`.** No packaged form repeats a field group, and the one repeating collection is a
`DataView` of server-side records that `GroupDetail` deliberately adds one row per POST. Indexed
error paths only start meaning something once `ApiError.fields` has a second consumer.

### 3. The form seam is four HTML attributes, not a library

`useTerpForm` / `rules()` / a `FormAdapter` are refused, and `zod` and `react-hook-form` with them.

The decisive measurement: **`minLength`, `maxLength` and `pattern` appear zero times** in
`react-core`, the example app and the template. The one client-side constraint in the whole codebase
is prose — a `hint="At least 16 characters"` on an `Input` that could carry `minLength={16}` and be
enforced by the browser. `Input` already spreads all three.

The dependency argument has to be made properly, because the usual version ("react-core has no
runtime dependencies") is false — it has two. The two that survive:

1. **react-core publishes source.** `exports` is `"./src/index.ts"`, compiled by the app's Vite. A
   `zod` in `dependencies` therefore puts zod's *types* in react-core's public surface, and an app
   pinning a different major gets two instances where `instanceof ZodError` fails silently across
   them. `@tanstack/react-router` survives this because it is reached through a seam
   (`buildAppRouter`, `useTerpNavigate`); a form library appears in every screen.
2. **It buys nothing missing.** `react-hook-form`'s value is uncontrolled-input performance on
   large forms. The largest packaged form is three fields. What was actually missing was the
   server's per-field message, and that is `ApiError.fields`.

### 4. Wording is a control

`restrictedElementGuidance` gains a `table` entry, its second after `dialog`. The precedent is ADR
0096 §4: "use ConfirmDialog" was wrong advice for an edit form, and the fix was the sentence rather
than the rule. "Use DataView" is wrong advice for a static five-row table *unless it names the
recipe* — `variant="embedded"` plus
`new InMemoryDataViewRepository(rows, { getRowId, getValue })`. An author
who reads advice that does not fit reaches for the raw element, so the lint message is where this
decision has to live.

### 5. Deferred, with a trigger

**A command palette.** ADR 0097 §4 names it, and every part is in hand: `AppShell` receives a
role-trimmed `nav`, `ConfirmDialog` proves the `<dialog>` + `showModal()` top-layer pattern,
`Combobox` has the filter-and-arrow-key listbox, `ICON_GLYPHS` has `search`. But an ADR sanction is
not a consumer. Nothing works around its absence, there is no search surface in `AppShell` at all,
and a flat seven-module nav is not a corpus worth a palette. **The trigger:** the first
app-supplied action corpus, or a nav that outgrows the rail. It must not imply record search either
way — that needs a provider seam *and* a backend endpoint, which is a capability, not a component.

**`Icon`'s `size` sizes the box, not the glyph.** `size="2rem"` renders a ~20px glyph in a 32px box.
The fix is one property and is zero-diff at the `1em` default, but it repaints the theme toggle, the
language switcher, every toast and the drawer close button. Deferred rather than missed, and now
cheaper than when it was deferred: the win32 baselines this repository could not re-record are
recordable again.

## Consequences

The marker inventory ends **one lower** than it started, and `INLINE_STYLE_SITES` is unchanged at
nine — while six user-visible gaps closed. That is the shape a component phase should have when the
survey is honest: most of the work is finding that the thing already exists, twice, or does not need
to exist at all.

Three new published names (`Avatar`, `ColumnWidth`, the `format` helpers), one breaking type
(`DataViewColumnMeta.width`), two new strings, two new glyphs, and **no new dependencies**.

The refusals above are not permanent. Each names what would change its mind, and the standing
instruction is the one this ADR opens with: bring a consumer, not a use case.
