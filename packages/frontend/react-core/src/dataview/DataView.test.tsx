// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataView } from "./DataView";
import { InMemoryDataViewRepository } from "./repositories/InMemoryDataViewRepository";
import { InMemoryViewStateRepository } from "./repositories/viewState";
import type { DataViewColumn, DataViewQuery, DataViewRepository } from "./types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

interface Ticket {
  id: string;
  title: string;
  status: string;
}

const TICKETS: Ticket[] = [
  { id: "1", title: "Broken printer", status: "open" },
  { id: "2", title: "VPN access", status: "closed" },
  { id: "3", title: "New laptop", status: "open" },
  { id: "4", title: "Password reset", status: "open" },
];

const COLUMNS: DataViewColumn<Ticket>[] = [
  { id: "title", header: "Title", accessor: (t) => t.title, meta: { mobileSlot: "title" } },
  { id: "status", header: "Status", accessor: (t) => t.status, meta: { mobileSlot: "status" } },
];

function inMemoryRepo(rows: Ticket[] = TICKETS) {
  return new InMemoryDataViewRepository(rows, {
    getRowId: (t) => t.id,
    getValue: (t, col) => t[col as keyof Ticket],
    searchFields: ["title"],
  });
}

describe("DataView states", () => {
  it("shows a loading skeleton, then the rows", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    expect(screen.getByRole("status", { name: "Loading…" })).toBeInTheDocument();
    expect(await screen.findByText("Broken printer")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading…" })).not.toBeInTheDocument();
    expect(screen.getByText("1–4 of 4 results")).toBeInTheDocument();
  });

  it("shows the empty state with the emptyActions slot", async () => {
    render(
      <DataView
        repository={inMemoryRepo([])}
        columns={COLUMNS}
        emptyMessage="No tickets."
        emptyActions={<button type="button">Reset</button>}
      />,
    );
    expect(await screen.findByText("No tickets.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });

  it("shows the error state when the repository rejects", async () => {
    const failing: DataViewRepository<Ticket> = {
      query: () => Promise.reject(new Error("boom")),
      getRowId: (t) => t.id,
      capabilities: { serverSide: false, search: false, searchScope: false },
    };
    render(<DataView repository={failing} columns={COLUMNS} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data.");
  });
});

describe("DataView server-side mode", () => {
  it("pushes pagination into the repository query and uses the returned total", async () => {
    const queries: DataViewQuery[] = [];
    const server: DataViewRepository<Ticket> = {
      query: (q) => {
        queries.push(q);
        const start = q.pagination.pageIndex * q.pagination.pageSize;
        return Promise.resolve({ rows: TICKETS.slice(start, start + q.pagination.pageSize), totalCount: 4 });
      },
      getRowId: (t) => t.id,
      capabilities: { serverSide: true, search: true, searchScope: false },
    };
    render(<DataView repository={server} columns={COLUMNS} initialPageSize={2} />);
    expect(await screen.findByText("Broken printer")).toBeInTheDocument();
    expect(screen.getByText("1–2 of 4 results")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("New laptop")).toBeInTheDocument();
    expect(queries.at(-1)?.pagination).toEqual({ pageIndex: 1, pageSize: 2 });
  });

  it("snaps an out-of-range page back to the last valid page", async () => {
    const queries: DataViewQuery[] = [];
    const server: DataViewRepository<Ticket> = {
      query: (q) => {
        queries.push(q);
        const start = q.pagination.pageIndex * q.pagination.pageSize;
        return Promise.resolve({ rows: TICKETS.slice(start, start + q.pagination.pageSize), totalCount: 4 });
      },
      getRowId: (t) => t.id,
      capabilities: { serverSide: true, search: true, searchScope: false },
    };
    const onPaginationChange = vi.fn();
    render(
      <DataView
        repository={server}
        columns={COLUMNS}
        serverQuery={{
          sorting: [],
          filters: [],
          search: "",
          pagination: { pageIndex: 49, pageSize: 2 }, // e.g. a stale ?page=50 deep link
          onSortingChange: vi.fn(),
          onFiltersChange: vi.fn(),
          onSearchChange: vi.fn(),
          onPaginationChange,
        }}
      />,
    );
    // The out-of-range query resolves empty, then pagination snaps to the last page.
    await waitFor(() =>
      expect(onPaginationChange).toHaveBeenCalledWith({ pageIndex: 1, pageSize: 2 }),
    );
    expect(queries.at(0)?.pagination).toEqual({ pageIndex: 49, pageSize: 2 });
  });
});

describe("DataView layout switching", () => {
  it("switches between table and cards via the explicit toggle", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    expect(await screen.findByRole("table")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Card view" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText("Broken printer")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Table view" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});

describe("DataView selection and batch actions", () => {
  it("selects across pages: page select, select-all mode, onSelectAll dispatch, reset on break", async () => {
    const onClick = vi.fn();
    const onSelectAll = vi.fn();
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        initialPageSize={2}
        enableSelection
        batchActions={[{ label: "Archive", onClick, onSelectAll, inline: true }]}
      />,
    );
    await screen.findByText("Broken printer");

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all rows on this page" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select all 4 results" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onSelectAll).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();

    // Breaking the page selection resets select-all-across-pages mode.
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select row" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick.mock.calls[0]?.[0]).toHaveLength(1);
  });

  it("clears the selection from the toolbar", async () => {
    render(
      <DataView repository={inMemoryRepo()} columns={COLUMNS} enableSelection />,
    );
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select row" })[0]!);
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.queryByText("1 selected")).not.toBeInTheDocument();
  });

  it("invalidates the selection when the query scope changes underneath it", async () => {
    const server: DataViewRepository<Ticket> = {
      query: (q) =>
        Promise.resolve({
          rows: TICKETS.filter((t) => t.title.includes(q.search)),
          totalCount: 4,
        }),
      getRowId: (t) => t.id,
      capabilities: { serverSide: true, search: true, searchScope: false },
    };
    const controlled = {
      sorting: [],
      filters: [],
      search: "",
      pagination: { pageIndex: 0, pageSize: 10 },
      onSortingChange: vi.fn(),
      onFiltersChange: vi.fn(),
      onSearchChange: vi.fn(),
      onPaginationChange: vi.fn(),
    };
    const { rerender } = render(
      <DataView repository={server} columns={COLUMNS} enableSelection serverQuery={controlled} />,
    );
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all rows on this page" }));
    expect(screen.getByText("4 selected")).toBeInTheDocument();

    // The search changes externally (e.g. URL back/forward) — a different result
    // set must never inherit the old "all results" selection.
    rerender(
      <DataView
        repository={server}
        columns={COLUMNS}
        enableSelection
        serverQuery={{ ...controlled, search: "laptop" }}
      />,
    );
    await waitFor(() => expect(screen.queryByText("4 selected")).not.toBeInTheDocument());
  });
});

describe("DataView row actions", () => {
  it("honours disabled/hidden predicates per row", async () => {
    const onDelete = vi.fn();
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        rowActionsLayout="inline"
        rowActions={(t) => [
          {
            label: "Delete",
            onClick: onDelete,
            variant: "destructive",
            disabled: (row: Ticket) => row.status === "closed",
            hidden: (row: Ticket) => row.id === "4",
          },
        ]}
      />,
    );
    await screen.findByText("Broken printer");

    const deleteButtons = screen.getAllByRole("button", { name: "Delete" });
    expect(deleteButtons).toHaveLength(3); // hidden for ticket 4
    expect(deleteButtons[1]).toBeDisabled(); // VPN access is closed

    fireEvent.click(deleteButtons[0]!);
    expect(onDelete).toHaveBeenCalledWith(TICKETS[0]);
  });

  it("does not trigger row click from an action cell", async () => {
    const onRowClick = vi.fn();
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        getRowLabel={(ticket) => ticket.title}
        onRowClick={onRowClick}
        rowActionsLayout="inline"
        rowActions={() => [{ label: "Open", onClick: vi.fn() }]}
      />,
    );
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getAllByRole("button", { name: "Open" })[0]!);
    expect(onRowClick).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Broken printer"));
    expect(onRowClick).toHaveBeenCalledWith(TICKETS[0]);
  });

  it("exposes record-labelled native activation buttons in table and card views", async () => {
    const onRowClick = vi.fn();
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        getRowLabel={(ticket) => ticket.title}
        onRowClick={onRowClick}
      />,
    );
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getByRole("button", { name: "Open details: Broken printer" }));
    expect(onRowClick).toHaveBeenLastCalledWith(TICKETS[0]);

    fireEvent.click(screen.getByRole("button", { name: "Card view" }));
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getByRole("button", { name: "Open details: Broken printer" }));
    expect(onRowClick).toHaveBeenLastCalledWith(TICKETS[0]);
  });
});

describe("DataView expandable rows", () => {
  it("toggles the full-width detail panel", async () => {
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        renderExpanded={(t) => <div>Detail: {t.title}</div>}
      />,
    );
    await screen.findByText("Broken printer");
    fireEvent.click(screen.getAllByRole("button", { name: "Expand row" })[0]!);
    expect(screen.getByText("Detail: Broken printer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse row" }));
    expect(screen.queryByText("Detail: Broken printer")).not.toBeInTheDocument();
  });
});

describe("DataView column resizing", () => {
  it("persists resized widths once, on pointer-up", async () => {
    const store = new InMemoryViewStateRepository();
    const save = vi.spyOn(store, "save");
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        viewId="tickets.list"
        viewStateRepository={store}
      />,
    );
    await screen.findByText("Broken printer");
    save.mockClear();

    const handle = screen.getAllByRole("separator")[0]!;
    fireEvent.pointerDown(handle, { clientX: 100 });
    fireEvent.pointerMove(window, { clientX: 140 });
    fireEvent.pointerMove(window, { clientX: 180 });
    expect(save).not.toHaveBeenCalled(); // no persistence writes per pointermove
    fireEvent.pointerUp(window);
    expect(save).toHaveBeenCalledTimes(1);
    expect(store.load("tickets.list")?.columnSizing.title).toBeGreaterThanOrEqual(60);
  });
});

describe("DataView search and view options", () => {
  it("filters via the toolbar search and clears with the × button", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    await screen.findByText("Broken printer");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "laptop" } });
    await waitFor(() => expect(screen.queryByText("Broken printer")).not.toBeInTheDocument());
    expect(screen.getByText("New laptop")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(await screen.findByText("Broken printer")).toBeInTheDocument();
  });

  it("hides and reorders columns from the view-options menu", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    await screen.findByText("Broken printer");

    fireEvent.click(screen.getByRole("button", { name: "View options" }));
    const menu = screen.getByRole("menu");
    fireEvent.click(within(menu).getByRole("checkbox", { name: "Status" }));
    expect(screen.queryByRole("columnheader", { name: /Status/ })).not.toBeInTheDocument();

    fireEvent.click(within(menu).getByRole("checkbox", { name: "Status" }));
    fireEvent.click(within(menu).getByRole("button", { name: "Move up: Status" }));
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers[0]).toContain("Status");
  });
});

describe("DataView embedded variant", () => {
  it("keeps real search controls but omits pagination and view controls", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} variant="embedded" />);
    await screen.findByText("Broken printer");
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
    expect(screen.queryByText(/of 4 results/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Card view" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Rows per page" })).not.toBeInTheDocument();
    // All rows rendered — the parent owns paging.
    expect(screen.getAllByRole("row")).toHaveLength(5);
  });

  it("does not render an empty toolbar band for a non-searchable embedded view", async () => {
    const repository: DataViewRepository<Ticket> = {
      query: async () => ({ rows: TICKETS, totalCount: TICKETS.length }),
      getRowId: (ticket) => ticket.id,
      capabilities: { serverSide: false, search: false, searchScope: false },
    };
    render(<DataView repository={repository} columns={COLUMNS} variant="embedded" />);
    await screen.findByText("Broken printer");
    expect(document.querySelector('[data-terp="dataview-toolbar"]')).not.toBeInTheDocument();
  });
});
