import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";
import { DataView } from "./dataview/DataView";
import type { DataViewRepository } from "./dataview/types";

interface Row {
  id: string;
  name: string;
}

const repository: DataViewRepository<Row> = {
  query: async () => ({ rows: [], totalCount: 0 }),
  getRowId: (row) => row.id,
  capabilities: { serverSide: false, search: false, searchScope: false },
};

describe("server rendering", () => {
  it("renders responsive shell and DataView defaults without browser globals", () => {
    expect(typeof window).toBe("undefined");

    const shell = renderToString(
      <AppShell
        title="Terp"
        nav={[{ label: "Home", to: "/", icon: "home" }]}
        renderLink={(item, children, context) => (
          <a href={item.to} style={context.style}>{children}</a>
        )}
      >
        <p>content</p>
      </AppShell>,
    );
    const view = renderToString(
      <DataView
        repository={repository}
        columns={[{ id: "name", header: "Name", accessor: (row) => row.name }]}
      />,
    );

    expect(shell).toContain("content");
    expect(shell).toContain("Home");
    expect(view).toContain('data-terp="dataview"');
  });
});
