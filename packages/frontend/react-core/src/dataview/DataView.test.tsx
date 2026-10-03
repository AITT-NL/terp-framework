// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOCALE_EN, LOCALE_NL, LanguageSwitcher, LocaleProvider } from "../locale";
import { DataView } from "./DataView";
import { DataViewPagination } from "./DataViewPagination";
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

  it("states no count while the total is unknown, rather than zero", async () => {
    // The defect: the footer computed its range from a totalCount that started at 0, so a
    // fresh view asserted "0–0 of 0 results" directly underneath its own loading skeleton.
    // A count is a fact, and that one was both unasked-for and usually wrong.
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    expect(screen.getByRole("status", { name: "Loading…" })).toBeInTheDocument();
    expect(screen.queryByText(/results/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0.*of.*0/)).not.toBeInTheDocument();
    // ... and the real count still arrives.
    expect(await screen.findByText("1–4 of 4 results")).toBeInTheDocument();
  });

  it("says no count when the query failed either, having none to report", async () => {
    // A failed refetch knows nothing about how many rows match now. Carrying the previous
    // number over, or falling back to zero, both present a guess as an answer.
    const failing: DataViewRepository<Ticket> = {
      capabilities: inMemoryRepo().capabilities,
      getRowId: (t) => t.id,
      query: () => Promise.reject(new Error("upstream is down")),
    };
    render(<DataView repository={failing} columns={COLUMNS} />);
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Loading…" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(/results/)).not.toBeInTheDocument();
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

  it("tints and stamps a row whose getRowTone returns a tone (row-level state)", async () => {
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        getRowTone={(t) => (t.status === "closed" ? "danger" : null)}
      />,
    );
    const toned = (await screen.findByText("VPN access")).closest("tr");
    expect(toned).toHaveAttribute("data-tone", "danger");
    const untinted = screen.getByText("Broken printer").closest("tr");
    expect(untinted).not.toHaveAttribute("data-tone");
  });

  it("claims data-clickable only when a row click is wired up", async () => {
    // The other half of a sheet rule no visual lane can see. The row marker is stamped
    // unconditionally — it has to be, or a toned row that is not clickable carries data-tone on
    // an element no selector reaches — so what separates a row Enter will open from a row that
    // merely contains a focusable checkbox is this attribute alone. The sheet's focus-within
    // tint is keyed on it, and styles.test.ts pins that end.
    const { unmount } = render(
      <DataView repository={inMemoryRepo()} columns={COLUMNS} enableSelection />,
    );
    const inert = (await screen.findByText("VPN access")).closest("tr");
    expect(inert).toHaveAttribute("data-terp", "dataview-row");
    expect(inert).not.toHaveAttribute("data-clickable");
    unmount();

    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        getRowLabel={(t) => t.title}
        onRowClick={() => {}}
      />,
    );
    const clickable = (await screen.findByText("VPN access")).closest("tr");
    expect(clickable).toHaveAttribute("data-clickable", "true");
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

  it("draws a chevron only on the rows that have something behind it", async () => {
    // `renderExpanded` is one prop for the whole view, so declaring it put a toggle on
    // every row -- including the ones where the only honest thing left to show is a
    // sentence saying there is nothing. Row actions, in the same interface, have taken a
    // row all along.
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        renderExpanded={(t) => <div>Detail: {t.title}</div>}
        isRowExpandable={(t) => t.title === "Broken printer"}
      />,
    );
    await screen.findByText("Broken printer");

    expect(screen.getAllByRole("button", { name: "Expand row" })).toHaveLength(1);
  });

  it("keeps every row expandable when no predicate is given", async () => {
    // The counter-case, so the assertion above cannot pass because the chevrons went away
    // altogether: the default is unchanged and every row still has one.
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        renderExpanded={(t) => <div>Detail: {t.title}</div>}
      />,
    );
    await screen.findByText("Broken printer");

    expect(screen.getAllByRole("button", { name: "Expand row" }).length).toBeGreaterThan(1);
  });

  it("drops the expand column when the predicate refuses every row", async () => {
    // A column of empty cells is worse than no column: it takes width from the data and
    // says nothing. One expandable row is enough to keep it, none is enough to lose it.
    render(
      <DataView
        repository={inMemoryRepo()}
        columns={COLUMNS}
        renderExpanded={(t) => <div>Detail: {t.title}</div>}
        isRowExpandable={() => false}
      />,
    );
    await screen.findByText("Broken printer");

    expect(screen.queryAllByRole("button", { name: "Expand row" })).toHaveLength(0);
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

  it("hides and reorders columns from the view-options panel", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    await screen.findByText("Broken printer");

    fireEvent.click(screen.getByRole("button", { name: "View options" }));
    // A group labelled by its own heading, not a menu. That is the fix for a critical
    // aria-required-children violation: role="menu" may own only menuitem-family children,
    // and this panel's content is a heading plus labelled checkboxes plus paired reorder
    // buttons — a form. The guard below is the regression test for it, because the violation
    // was invisible for as long as nothing rendered the panel open.
    const panel = screen.getByRole("group", { name: "Columns" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Status" }));
    expect(screen.queryByRole("columnheader", { name: /Status/ })).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("checkbox", { name: "Status" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Move up: Status" }));
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers[0]).toContain("Status");
  });

  it("names the view-options trigger from its visible label, not an override", async () => {
    // The trigger used to take its accessible name from an aria-label the menu primitive
    // applied, which is the shape that hides a visible label from assistive tech when the two
    // drift. It is now named by its own content, so the announced name IS the rendered one.
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} />);
    await screen.findByText("Broken printer");
    const trigger = screen.getByRole("button", { name: "View options" });
    expect(trigger).not.toHaveAttribute("aria-label");
    expect(trigger).toHaveTextContent("View options");
    // A disclosure, so this is the whole contract: expanded state plus the panel it controls.
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-haspopup");
  });
});

describe("DataView embedded variant", () => {
  it("keeps real search controls but omits pagination and view controls", async () => {
    render(<DataView repository={inMemoryRepo()} columns={COLUMNS} variant="embedded" />);
    await screen.findByText("Broken printer");
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
    expect(screen.queryByText(/of 4 results/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Card view" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rows per page" })).not.toBeInTheDocument();
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

describe("DataView search scope", () => {
  // Nothing rendered this branch before the search-scope specimen existed: the control is
  // behind `search.trim() !== ""`, and every other test and specimen starts with an empty box.
  // That is how a control shipped announcing itself as a toggle button whose state is also its
  // label.
  const scopedRepo = (): DataViewRepository<Ticket> => ({
    query: async () => ({ rows: TICKETS, totalCount: TICKETS.length }),
    getRowId: (ticket) => ticket.id,
    capabilities: { serverSide: true, search: true, searchScope: true },
  });

  it("swaps the label rather than claiming to be a toggle button", async () => {
    const onBroadenedChange = vi.fn();
    const { rerender } = render(
      <DataView
        repository={scopedRepo()}
        columns={COLUMNS}
        searchScope={{
          broadened: false,
          onBroadenedChange,
          label: "Search everything",
          broadenedLabel: "Searching everything",
        }}
      />,
    );
    await screen.findByText("Broken printer");
    // The control needs a search term, so type one.
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "printer" } });
    const narrow = await screen.findByRole("button", { name: "Search everything" });
    // The state is the label. Encoding it a second time in aria-pressed announces it twice
    // and lets the two disagree, because both labels are caller-supplied.
    expect(narrow).not.toHaveAttribute("aria-pressed");
    fireEvent.click(narrow);
    expect(onBroadenedChange).toHaveBeenCalledWith(true);

    rerender(
      <DataView
        repository={scopedRepo()}
        columns={COLUMNS}
        searchScope={{
          broadened: true,
          onBroadenedChange,
          label: "Search everything",
          broadenedLabel: "Searching everything",
        }}
      />,
    );
    const broad = await screen.findByRole("button", { name: "Searching everything" });
    expect(broad).not.toHaveAttribute("aria-pressed");
    // And the attribute is now this component's alone on the two layout toggles, which is the
    // enumeration the shared icon-button hover guard is safe by.
    expect(document.querySelectorAll("[aria-pressed]")).toHaveLength(2);
    for (const toggle of document.querySelectorAll("[aria-pressed]")) {
      expect(toggle.getAttribute("data-terp")).toBe("iconbutton");
    }
  });
});

describe("DataView localisation", () => {
  // DataView's strings are framework strings: the `dataView*` keys of TerpStrings. They used to
  // be a separate English table that only the per-instance `strings` prop could change, so a
  // DataView under a Dutch LocaleProvider still said "Search…" and "1–4 of 4 results" — the
  // framework's own admin screens included — while every locale gate reported the catalog
  // complete.
  afterEach(() => {
    // The switcher persists its choice; the next test must not open in it.
    window.localStorage.clear();
  });

  it("speaks the app's locale without a strings prop, and follows a switch", async () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }}>
        <LanguageSwitcher />
        <DataView repository={inMemoryRepo()} columns={COLUMNS} />
      </LocaleProvider>,
    );
    expect(await screen.findByText("1–4 of 4 results")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Language" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Nederlands" }));

    expect(await screen.findByText("1–4 van 4 resultaten")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Zoeken…" })).toHaveAttribute(
      "placeholder",
      "Zoeken…",
    );
    expect(screen.getByRole("button", { name: "Rijen per pagina" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Weergaveopties" })).toBeInTheDocument();
    expect(screen.queryByText(/results/)).not.toBeInTheDocument();
  });

  it("says a single result in the singular, in both shipped languages", async () => {
    // The footer used to read "1–1 of 1 results" and "1–1 van 1 resultaten": one sentence for
    // every count, with the plural noun in it.
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }}>
        <LanguageSwitcher />
        <DataView repository={inMemoryRepo(TICKETS.slice(0, 1))} columns={COLUMNS} />
      </LocaleProvider>,
    );
    expect(await screen.findByText("1–1 of 1 result")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Language" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Nederlands" }));

    expect(await screen.findByText("1–1 van 1 resultaat")).toBeInTheDocument();
  });

  it("renders an instance's own range as given, with no plural form chosen", async () => {
    // An override is one UiText, the instance's own wording; only the locale's has forms.
    render(
      <DataView
        repository={inMemoryRepo(TICKETS.slice(0, 1))}
        columns={COLUMNS}
        strings={{ resultsRange: "{from}–{to} / {total} tickets" }}
      />,
    );
    expect(await screen.findByText("1–1 / 1 tickets")).toBeInTheDocument();
  });

  it("lets a per-instance string win over the locale", async () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }} defaultLocale="nl">
        <DataView
          repository={inMemoryRepo()}
          columns={COLUMNS}
          strings={{ searchPlaceholder: "Zoek een ticket…" }}
        />
      </LocaleProvider>,
    );
    // The rest of the view still follows the locale; only the overridden key does not.
    expect(await screen.findByText("1–4 van 4 resultaten")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Zoek een ticket…" })).toBeInTheDocument();
    expect(screen.queryByRole("searchbox", { name: "Zoeken…" })).not.toBeInTheDocument();
  });

  it("localises a sub-component rendered outside any DataView", () => {
    // The parts are exported for hand-built compositions, and outside a DataView there is no
    // provider above them. The context's default used to be a finished English set with a
    // resolver that ignored the locale, so this path stayed English whatever the provider did.
    render(
      <LocaleProvider locales={{ en: LOCALE_EN, nl: LOCALE_NL }} defaultLocale="nl">
        <DataViewPagination
          pagination={{ pageIndex: 1, pageSize: 10 }}
          totalCount={45}
          onPaginationChange={() => {}}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("11–20 van 45 resultaten")).toBeInTheDocument();
    expect(screen.getByText("Pagina 2 van 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volgende pagina" })).toBeInTheDocument();
  });
});

describe("DataView as a panel (ADR 0169 §5)", () => {
  it("names itself in a heading and counts its results once it has read them", async () => {
    // Mutation: drop the count from the heading, and the name stays "Tickets".
    render(<DataView title="Tickets" repository={inMemoryRepo()} columns={COLUMNS} />);
    // No number while the first page loads: the count is a claim, and nothing was read yet.
    expect(screen.getByRole("heading", { level: 3, name: "Tickets" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 3, name: "Tickets 4" })).toBeInTheDocument();
  });

  it("prints the count in the app's locale", async () => {
    const many = Array.from({ length: 1234 }, (_, index) => ({
      id: String(index),
      title: `Ticket ${index}`,
      status: "open",
    }));
    render(
      <LocaleProvider locales={{ nl: LOCALE_NL, en: LOCALE_EN }} defaultLocale="nl">
        <DataView title="Tickets" repository={inMemoryRepo(many)} columns={COLUMNS} />
      </LocaleProvider>,
    );
    expect(await screen.findByRole("heading", { level: 3, name: "Tickets 1.234" })).toBeInTheDocument();
  });

  it("claims no count over an error, even with an earlier count in hand", async () => {
    // A failed query sets the error and leaves the last total where it was, so after one good
    // page and one failed search the view still holds "4" -- a number about rows it is no
    // longer showing. Mutation: drop the error from the condition, and the heading keeps "4".
    let calls = 0;
    const base = inMemoryRepo();
    const flaky: DataViewRepository<Ticket> = {
      capabilities: base.capabilities,
      getRowId: (t) => t.id,
      query: (query) =>
        calls++ === 0 ? base.query(query) : Promise.reject(new Error("upstream is down")),
    };
    render(<DataView title="Tickets" repository={flaky} columns={COLUMNS} searchDebounceMs={0} />);
    await screen.findByRole("heading", { level: 3, name: "Tickets 4" });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "printer" } });
    await waitFor(() =>
      expect(document.querySelector('[data-terp="dataview-error"]')).not.toBeNull(),
    );
    expect(screen.getByRole("heading", { level: 3, name: "Tickets" })).toBeInTheDocument();
    expect(document.querySelector('[data-terp="dataview-count"]')).toBeNull();
  });

  it("titles an embedded view too, above its toolbar", async () => {
    render(
      <DataView
        title="Tickets"
        variant="embedded"
        repository={inMemoryRepo()}
        columns={COLUMNS}
        toolbarContent={<button type="button">Add ticket</button>}
      />,
    );
    const heading = await screen.findByRole("heading", { level: 3, name: "Tickets 4" });
    const add = screen.getByRole("button", { name: "Add ticket" });
    expect(heading.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("DataView's cell presentations (ADR 0169 §5)", () => {
  interface Group {
    id: string;
    name: string;
    members: number;
    active: boolean;
  }
  const GROUPS: Group[] = [
    { id: "a", name: "Operations", members: 12, active: true },
    { id: "b", name: "Finance", members: 3, active: false },
    { id: "c", name: "Support", members: 6, active: true },
  ];
  const repo = () =>
    new InMemoryDataViewRepository(GROUPS, {
      getRowId: (g) => g.id,
      getValue: (g, col) => g[col as keyof Group],
      searchFields: ["name"],
    });

  it("puts a status dot before the cell's text, in the row's tone", async () => {
    const columns: DataViewColumn<Group>[] = [
      { id: "name", header: "Name", accessor: (g) => g.name },
      {
        id: "active",
        header: "Status",
        accessor: (g) => (g.active ? "Active" : "Paused"),
        status: (g) => (g.active ? "success" : "neutral"),
      },
    ];
    render(<DataView repository={repo()} columns={columns} />);
    const paused = await screen.findByText("Paused");
    const status = paused.closest('[data-terp="dataview-status"]')!;
    const dot = status.querySelector('[data-terp="dataview-status-dot"]')!;
    expect(dot).toHaveAttribute("data-tone", "neutral");
    expect(dot).toHaveAttribute("aria-hidden", "true");
    // The text is the word the dot stands for, and it is the cell's whole accessible text.
    expect(status.textContent).toBe("Paused");
  });

  it("draws no dot beside a cell with no text, since the dot stands for a word", async () => {
    // Mutation: drop the empty-content guard, and the empty cell gets a bare dot.
    const columns: DataViewColumn<Group>[] = [
      { id: "name", header: "Name", accessor: (g) => g.name },
      { id: "note", header: "Note", accessor: () => null, status: () => "danger" },
    ];
    render(<DataView repository={repo()} columns={columns} />);
    await screen.findByText("Operations");
    expect(document.querySelector('[data-terp="dataview-status-dot"]')).toBeNull();
  });

  it("draws a numeric column as bars scaled to the largest value shown", async () => {
    // Mutation: scale to the row's own value, and every bar is full.
    const columns: DataViewColumn<Group>[] = [
      { id: "name", header: "Name", accessor: (g) => g.name },
      { id: "members", header: "Members", accessor: (g) => g.members, bar: true },
    ];
    render(<DataView repository={repo()} columns={columns} />);
    await screen.findByText("Operations");
    const meters = screen.getAllByRole("meter", { name: "Members" });
    expect(meters.map((meter) => meter.getAttribute("max"))).toEqual(["12", "12", "12"]);
    expect(meters.map((meter) => meter.getAttribute("aria-valuetext"))).toEqual(["12", "3", "6"]);
  });

  it("scales bars to a declared max, and formats the printed value", async () => {
    const columns: DataViewColumn<Group>[] = [
      { id: "name", header: "Name", accessor: (g) => g.name },
      {
        id: "members",
        header: "Members",
        accessor: (g) => g.members * 1000,
        bar: { max: 20_000 },
      },
    ];
    render(<DataView repository={repo()} columns={columns} />);
    await screen.findByText("Operations");
    const meters = screen.getAllByRole("meter", { name: "Members" });
    expect(meters[0]).toHaveAttribute("max", "20000");
    // A plain number in the app's locale -- grouped, where the default cell printed "12000".
    expect(meters[0]).toHaveAttribute("aria-valuetext", "12,000");
  });

  it("renders the same presentation in the card layout", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    const columns: DataViewColumn<Group>[] = [
      { id: "name", header: "Name", accessor: (g) => g.name, meta: { mobileSlot: "title" } },
      {
        id: "active",
        header: "Status",
        accessor: (g) => (g.active ? "Active" : "Paused"),
        status: (g) => (g.active ? "success" : "neutral"),
        meta: { mobileSlot: "status" },
      },
    ];
    try {
      render(<DataView repository={repo()} columns={columns} />);
      await screen.findByText("Operations");
      expect(document.querySelector('[data-terp="dataview-card-list"]')).not.toBeNull();
      const card = screen.getByText("Paused").closest('[data-terp="dataview-card-status"]')!;
      expect(card.querySelector('[data-terp="dataview-status-dot"]')).toHaveAttribute(
        "data-tone",
        "neutral",
      );
    } finally {
      window.matchMedia = original;
    }
  });
});

describe("DataView's status dots are declared pairings", () => {
  it("colours each toned dot in a pairing the contrast gate holds against the surface", async () => {
    // A dot is the graphical object SC 1.4.11 asks 3:1 of, and the gate measures only what
    // token-pairs.json declares. Mutation: colour the success dot with the accent, and no
    // pairing holds it.
    const { TERP_STYLES_CSS } = await import("../styles");
    const pairs = (await import("../../../contract/token-pairs.json")).default as {
      nonTextPairs: { fg?: string; bg?: string }[];
    };
    for (const tone of ["info", "success", "warning", "danger"]) {
      const selector = `[data-terp="dataview-status-dot"][data-tone="${tone}"]`;
      const at = TERP_STYLES_CSS.indexOf(`${selector} {`);
      expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
      const body = TERP_STYLES_CSS.slice(at, TERP_STYLES_CSS.indexOf("}", at));
      const fg = /background: var\((--[a-z0-9-]+)\)/.exec(body)![1]!;
      expect(
        pairs.nonTextPairs.some((pair) => pair.fg === fg && pair.bg === "--color-bg-surface"),
        `${tone}: ${fg} on the surface`,
      ).toBe(true);
    }
  });
});
