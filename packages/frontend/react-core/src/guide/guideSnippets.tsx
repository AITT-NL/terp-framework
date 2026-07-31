// Typechecked guide snippets.
//
// `terp guide <topic>` is the first thing the golden rules point an author at, so a
// snippet in it that does not compile is worse than no snippet at all — this file
// shipped three lines of a DataView API that never existed. The blocks below are the
// real code the guide prints, compiled by the workspace typecheck and pinned to the
// guide text by tests/architecture/test_guide_snippets.py: change one and the other
// fails. Keep the block bodies byte-identical to the guide (modulo indentation).
import { useMemo } from "react";

import { DataView, InMemoryDataViewRepository } from "../dataview";
import type { DataViewColumn } from "../dataview";

interface Row {
  id: string;
  title: string;
  status: string;
}

export function GuideDataViewSnippet({ rows }: { rows: Row[] }) {
  const columns: DataViewColumn<Row>[] = [
    { id: "title", header: "Title", accessor: (r) => r.title },
    { id: "status", header: "Status", accessor: (r) => r.status },
  ];
  // terp-guide-snippet: dataview
  const repo = useMemo(
    () =>
      new InMemoryDataViewRepository(rows, {
        getRowId: (r) => r.id,
        getValue: (r, col) => r[col as keyof Row],
        searchFields: ["title", "status"],
      }),
    [rows],
  );
  // terp-guide-snippet-end
  return (
    // terp-guide-snippet: dataview
    <DataView repository={repo} columns={columns} viewId="notes.list" />
    // terp-guide-snippet-end
  );
}
