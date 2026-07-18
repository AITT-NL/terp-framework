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
} from "@terp/react-core";
import type { DataViewColumn } from "@terp/react-core";

interface Ticket { id: string; title: string; status: string; created: string }

const columns: DataViewColumn<Ticket>[] = [
  { id: "title", header: "Title", accessor: (t) => t.title, meta: { mobileSlot: "title" } },
  { id: "status", header: "Status", accessor: (t) => t.status, meta: { mobileSlot: "status" } },
  { id: "created", header: "Created", accessor: (t) => t.created, meta: { mobileSlot: "date", width: 120 } },
];

const repository = new InMemoryDataViewRepository(tickets, {
  getRowId: (t) => t.id,
  getValue: (t, col) => t[col as keyof Ticket],
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
import { DataView, HttpDataViewRepository, useServerDataView, unwrap } from "@terp/react-core";

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

- **System columns** are auto-injected in a fixed order — expand toggle, selection
  checkbox, user columns, row-actions (sr-only header) — pinned to narrow widths and
  never hideable/reorderable/resizable.
- **Column resizing**: drag the header handle; widths update live with no persistence
  writes per pointermove and are persisted once, on pointer-up. Width precedence:
  pinned system columns → user-resized → static `meta.width` hint → auto.
- **Select-all-across-pages**: after selecting the whole page the toolbar offers
  "Select all N results"; batch actions then invoke their `onSelectAll` variant. The
  mode resets whenever the page selection is broken.
- **Responsive**: auto-switches to the stacked card layout at the mobile breakpoint
  until the user chooses a layout explicitly (manual choice wins). Cards are composed
  from `meta.mobileSlot` (`title` / `subtitle` / `status` / `date`), with
  `renderCard(row)` as a full escape hatch; selection, actions and expansion keep
  working in card view.
- **Variants**: `variant="embedded"` renders a plain compact view (no view toggle, no
  page-size selector, no pagination footer, all rows) for panels/detail sections.
- **i18n**: no hard-coded user-facing strings — every label is a `UiText` routed
  through the app's `UiTextProvider` resolver, with defaults overridable per instance
  via the `strings` prop.

## Files

- `DataView.tsx` — composition only
- `DataViewToolbar` / `DataViewPagination` / `DataViewColumnSettings` /
  `DataViewRowActions` / `DataViewExpandableRow` / `DataViewCardList` / `DataViewTable`
- `repositories/` — the interfaces' implementations
- `hooks/` — `useDataViewState`, `useServerDataView`, `useViewSearch`, `useDataViewQuery`
