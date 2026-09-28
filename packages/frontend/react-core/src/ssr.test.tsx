import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";
import { DataView } from "./dataview/DataView";
import type { DataViewRepository } from "./dataview/types";
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";

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
        renderLink={(item, children) => <a href={item.to}>{children}</a>}
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

  it("renders a localised DataView without writing to a document that is not there", () => {
    // LocaleProvider keeps <html lang> on the active locale, and there is no `document` on the
    // server. The write lives in an effect, which server rendering never runs; moved into the
    // render body it throws here. And the DataView's own copy is already Dutch in the markup,
    // because its strings come from the same table the locale translates.
    const view = renderToString(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }} defaultLocale="nl">
        <DataView
          repository={repository}
          columns={[{ id: "name", header: "Name", accessor: (row) => row.name }]}
        />
      </LocaleProvider>,
    );

    expect(view).toContain('aria-label="Laden…"');
  });
});
