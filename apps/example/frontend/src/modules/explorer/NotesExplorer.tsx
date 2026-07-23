import {
  DataView,
  HttpDataViewRepository,
  OverviewPage,
  unwrap,
  useServerDataView,
  useTerpClient,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
import { useMemo } from "react";

import type { components, paths } from "../../api/schema";

type NoteRead = components["schemas"]["NoteRead"];

const columns: DataViewColumn<NoteRead>[] = [
  { id: "title", header: "Title", accessor: (n) => n.title, meta: { mobileSlot: "title" } },
  { id: "body", header: "Body", accessor: (n) => n.body, meta: { mobileSlot: "subtitle" } },
  {
    id: "created_at",
    header: "Created",
    accessor: (n) => n.created_at,
    cell: (n) => new Date(n.created_at).toLocaleDateString(),
    meta: { mobileSlot: "date", width: 120 },
  },
];

/**
 * The server-side DataView example: an {@link HttpDataViewRepository} whose injected
 * request adapter maps the emitted query to the notes endpoint's `skip`/`limit`
 * parameters over the typed contract client. Pagination lives in the URL via
 * {@link useServerDataView}, so the page deep-links and survives reloads.
 */
export function NotesExplorer() {
  const client = useTerpClient<paths>();
  const serverQuery = useServerDataView({ initialPageSize: 10 });

  const repository = useMemo(
    () =>
      new HttpDataViewRepository<NoteRead>({
        getRowId: (n) => n.id,
        // The notes endpoint pages but does not search/sort yet; advertise that so
        // the DataView hides the search box (the repo stays the single source of truth).
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/notes/", {
              params: { query: { skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    [client],
  );

  return (
    <OverviewPage title="Notes explorer">
      <DataView<NoteRead>
        viewId="explorer.notes"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
      />
    </OverviewPage>
  );
}
