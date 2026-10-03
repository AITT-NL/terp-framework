# DataView

The single sanctioned surface for rendering data collections in a Terp app: a
repository-driven, token-styled table/card view with search, sorting, pagination,
column management (show/hide, reorder, resize), selection with batch actions, per-row
actions, expandable rows, a responsive card layout and persisted view preferences.

`DataView` never fetches, never touches `localStorage`, and never knows whether data
is client-side or server-side. All data access goes through a **data repository** and
all preference persistence through a **view-state repository** — adding a new data
source or preference store never requires modifying any component file (dependency
inversion / open-closed).

`variant="embedded"` removes pagination and view controls. When its repository
is non-searchable and no selection, filter, or custom controls exist, DataView
also omits the toolbar band entirely so related empty collections add no blank
chrome.

## Quick start (client-side data)

```tsx
import {
  DataView,
  InMemoryDataViewRepository,
  LocalStorageViewStateRepository,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";

interface Ticket { id: string; title: string; status: string; created: string }

const columns: DataViewColumn<Ticket>[] = [
  { id: "title", header: "Title", accessor: (t) => t.title, meta: { mobileSlot: "title" } },
  { id: "status", header: "Status", accessor: (t) => t.status, meta: { mobileSlot: "status" } },
  { id: "created", header: "Created", accessor: (t) => t.created, meta: { mobileSlot: "date", width: "sm" } },
];

const repository = new InMemoryDataViewRepository(tickets, {
  getRowId: (t) => t.id,
  // Annotate the field parameter and `searchFields` is checked at compile time —
  // a misspelled entry otherwise resolves to undefined for every row, so search
  // silently never matches it. searchFields entries are the names getValue
  // understands (typically column ids).
  getValue: (t, col: keyof Ticket & string) => t[col],
  searchFields: ["title", "status"],
});

<DataView<Ticket>
  viewId="tickets.list"                                   // stable key for persisted preferences
  repository={repository}
  viewStateRepository={new LocalStorageViewStateRepository()}
  columns={columns}
  getRowLabel={(t) => t.title}                         // required with onRowClick (a11y name)
  onRowClick={(t) => navigate(t.id)}
  enableSelection
  batchActions={[{ label: "Archive", onClick: archive, onSelectAll: archiveAll, inline: true }]}
  rowActions={(t) => [
    { label: "Delete", variant: "destructive", onClick: remove, disabled: (t) => t.status === "closed" },
  ]}
  searchDebounceMs={300}
  pageSizeOptions={[10, 25, 50, 100]}
  renderExpanded={(t) => <TicketPreview ticket={t} />}
/>
```

## Server-side data

Server-side views keep sorting/filter/pagination in the URL via `useServerDataView`
(deep-linkable, survives reloads); the repository maps the emitted `DataViewQuery` to
API parameters through an injectable request adapter:

```tsx
import { DataView, HttpDataViewRepository, useServerDataView, unwrap } from "@terpjs/react-core";

const repository = new HttpDataViewRepository<NoteRead>({
  getRowId: (n) => n.id,
  request: async ({ skip, limit }, signal) => {
    const page = unwrap(await client.GET("/api/v1/notes/", { params: { query: { skip, limit } }, signal }));
    return { items: page.items, total: page.total };
  },
});

function NotesPage() {
  const serverQuery = useServerDataView({ initialPageSize: 25 });
  return <DataView repository={repository} columns={columns} serverQuery={serverQuery} />;
}
```

## The repository interfaces

### `DataViewRepository<T>` (data access)

| Member | Meaning |
|---|---|
| `query(q, signal?)` | Return one `{ rows, totalCount }` page for a `DataViewQuery` (pagination, sorting, filters, search, searchBroadened). |
| `getRowId(row)` | Stable row identity — selection/expansion survive re-sorts and refetches. |
| `capabilities.serverSide` | `true` → the repo does sorting/filtering/paging per query; `false` → it owns a full client-side data set. |
| `capabilities.search` | Whether the toolbar search box renders. |
| `capabilities.searchScope` | Whether the broadened "search everything" toggle is supported. |
| `getFacetedValues?(columnId)` | Optional: distinct values of a column (client-side facets). |

Implementations shipped: `InMemoryDataViewRepository` (wraps a plain array;
filter/search/sort/page client-side) and `HttpDataViewRepository` (maps the query to
`skip = pageIndex * pageSize`, `limit = pageSize`, sort/filter/search params and
delegates the transport to an injectable adapter).

### `ViewStateRepository` (persisted preferences)

`load(viewId)` / `save(viewId, state)` for everything the user customises: column
visibility, order, resized widths, and — for client-side views — sorting, filters and
search. Implementations shipped: `LocalStorageViewStateRepository` (schema-validated,
versioned envelope; corrupt data falls back to defaults) and
`InMemoryViewStateRepository` (tests, or views without a `viewId`).

## Behaviour notes

- **Default cell rendering** is shared by the table and the card layouts, so a column reads
  the same on a desktop and a phone: `null` / `undefined` render nothing, a `Date` renders
  through the app's locale, and anything else is `String(value)`. Pass `cell` to override.
- **Dates and numbers** in a `cell` renderer should go through `useFormatDate` /
  `useFormatDateTime` / `useFormatNumber`; `toLocaleDateString()` with no argument asks the
  visitor's browser rather than the app, and a repo-wide check refuses it.
- **System columns** are auto-injected in a fixed order — expand toggle, selection
  checkbox, user columns, row-actions (sr-only header) — pinned to narrow widths and
  never hideable/reorderable/resizable.
- **Column resizing**: drag the header handle; widths update live with no persistence
  writes per pointermove and are persisted once, on pointer-up. Width precedence:
  pinned system columns → user-resized → declared `meta.width` step → auto.
- **Declared column tracks**: `meta.width` is a step (`"xs"` / `"sm"` / `"md"`), not a
  length, and it binds as a **minimum** — under `table-layout: auto` a specified width is
  only a preference the algorithm shrinks to fit, so the px hint this replaced did nothing
  at all. A user resize replaces the step outright rather than competing with it: a resized
  column stops carrying the attribute, so the floor can never spring a drag back.
- **A titled collection** (ADR 0169 §5): `title` renders the collection's heading — an
  `<h3>`, the level a `Card` gives a section — with its count beside it once the repository has
  said how many there are: not while the first page loads, and not over an error. The count is
  part of the heading's name ("Members 12") and prints in the app's locale. Use it for a
  collection that is one section of a page; an overview whose page title already names the
  collection leaves it off.
- **Cell presentations** (ADR 0169 §5), on a column and the same in the table and the cards:
  `status: (row) => tone | null` puts a dot of that tone before the cell's text — the quiet
  form of a status column, where most rows are fine and a pill on every one is noise; the text
  is the word the dot stands for, so an empty cell gets none. `bar: true` (or
  `{ max, format }`) draws the column's number as a `Meter` scaled to the largest value among
  the rows shown — or to `max` — with the value printed beside it in the app's locale; a row
  whose value is not a number renders as text, and a `cell` renderer is not used for a bar. A
  percent column is drawn against 100%, its rates' own range, because a `Meter` prints a
  percentage as the share of its range; a `max` beside a percent format is refused.
  `history: (row) => runs` draws each row's recent runs as a `StatusHistory` — one cell per run,
  the latest ending in words — for a collection of things that run; a row with no runs renders
  none.
- **Row tone**: `getRowTone={(row) => tone | null}` marks the *row* as being in a
  state (a refused link, a failed run) — the right altitude when the verdict belongs
  to the record, not to one of its cells. The row/card is tinted with the tone's soft
  token (the same one `Badge` uses) and stamped `data-tone`; a toned row's tint
  outranks the selection tint. Keep cell-level `Badge`s for statuses that belong to a
  column.
- **Select-all-across-pages**: after selecting the whole page the toolbar offers
  "Select all N results"; batch actions then invoke their `onSelectAll` variant. The
  mode resets whenever the page selection is broken.
- **Responsive**: auto-switches to the stacked card layout at the mobile breakpoint
  until the user chooses a layout explicitly (manual choice wins). Cards are composed
  from `meta.mobileSlot` (`title` / `subtitle` / `status` / `date`), with
  `renderCard(row)` as a full escape hatch; selection, actions and expansion keep
  working in card view.
- **Density**: `density="compact"` stamps `data-density="compact"` on the root, which
  re-scopes the live density tokens for the whole subtree — cell padding here, plus the
  control heights `Button`, `Input` and `Select` already read, so the toolbar tightens
  with the table. `"comfortable"` is the default and stamps no attribute, because
  comfortable is what the token sheet declares on `:root`; the consequence is that
  `density="comfortable"` cannot make one view comfortable inside a compact subtree.
- **Variants**: `variant="embedded"` renders a plain compact view (no view toggle, no
  page-size selector, no pagination footer, all rows) for panels/detail sections.
- **i18n**: no hard-coded user-facing strings. The defaults are framework strings — the
  `dataView*` keys of `TerpStrings` — so a DataView follows the app's `LocaleProvider` like
  the rest of the chrome, and `LOCALE_NL` translates them. The `strings` prop overrides a key
  for one instance and wins over the locale; every value is a `UiText` resolved through the
  active resolver.

## Files

- `DataView.tsx` — composition only
- `DataViewToolbar` / `DataViewPagination` / `DataViewColumnSettings` /
  `DataViewRowActions` / `DataViewExpandableRow` / `DataViewCardList` / `DataViewTable`
- `repositories/` — the interfaces' implementations
- `hooks/` — `useDataViewState`, `useServerDataView`, `useViewSearch`, `useDataViewQuery`
