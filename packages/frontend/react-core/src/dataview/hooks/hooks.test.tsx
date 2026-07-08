// @vitest-environment jsdom
import { cleanup, renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useViewSearch } from "./useViewSearch";
import { useDataViewState } from "./useDataViewState";
import { useServerDataView } from "./useServerDataView";
import { InMemoryViewStateRepository } from "../repositories/viewState";
import type { DataViewColumn } from "../types";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

describe("useViewSearch", () => {
  it("emits immediately without a debounce", () => {
    const onChange = vi.fn();
    const { result } = renderHook(() => useViewSearch("", onChange));
    act(() => result.current.setInputValue("a"));
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("debounces emissions while keeping the input immediate", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const { result } = renderHook(() => useViewSearch("", onChange, 300));

    act(() => result.current.setInputValue("p"));
    act(() => result.current.setInputValue("pr"));
    expect(result.current.inputValue).toBe("pr");
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(300));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("pr");
  });

  it("clear() cancels the pending debounce and emits \"\" immediately", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const { result } = renderHook(() => useViewSearch("", onChange, 300));
    act(() => result.current.setInputValue("x"));
    act(() => result.current.clear());
    expect(onChange).toHaveBeenCalledWith("");
    act(() => vi.advanceTimersByTime(500));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("syncs external value changes back into the input", () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useViewSearch(value, () => undefined),
      { initialProps: { value: "" } },
    );
    rerender({ value: "reset" });
    expect(result.current.inputValue).toBe("reset");
  });

  it("an external reset cancels a pending debounced emit", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useViewSearch(value, onChange, 300),
      { initialProps: { value: "x" } },
    );
    act(() => result.current.setInputValue("xy"));
    rerender({ value: "" }); // e.g. a caller-driven "clear filters"
    act(() => vi.advanceTimersByTime(300));
    expect(onChange).not.toHaveBeenCalled(); // "xy" never resurrects the cleared search
    expect(result.current.inputValue).toBe("");
  });
});

interface Row {
  id: string;
  title: string;
  status: string;
}

const COLUMNS: DataViewColumn<Row>[] = [
  { id: "title", header: "Title" },
  { id: "status", header: "Status" },
  { id: "created", header: "Created" },
];

function renderState(viewStateRepository: InMemoryViewStateRepository, viewId = "v") {
  return renderHook(() =>
    useDataViewState<Row>({
      viewId,
      columns: COLUMNS,
      viewStateRepository,
      serverSide: false,
      initialPageSize: 10,
    }),
  );
}

describe("useDataViewState", () => {
  it("toggles sort asc → desc → none", () => {
    const { result } = renderState(new InMemoryViewStateRepository());
    act(() => result.current.toggleSort("title"));
    expect(result.current.sorting).toEqual([{ id: "title", desc: false }]);
    act(() => result.current.toggleSort("title"));
    expect(result.current.sorting).toEqual([{ id: "title", desc: true }]);
    act(() => result.current.toggleSort("title"));
    expect(result.current.sorting).toEqual([]);
  });

  it("persists column sizing once per commit and restores it", () => {
    const store = new InMemoryViewStateRepository();
    const save = vi.spyOn(store, "save");
    const first = renderState(store);
    act(() => first.result.current.commitColumnSizing({ title: 240, status: 120 }));
    expect(save).toHaveBeenCalledTimes(1);
    expect(first.result.current.columnSizing).toEqual({ title: 240, status: 120 });

    const second = renderState(store);
    expect(second.result.current.columnSizing).toEqual({ title: 240, status: 120 });
  });

  it("persists visibility and ordering, and restores effective column order", () => {
    const store = new InMemoryViewStateRepository();
    const first = renderState(store);
    act(() => first.result.current.setColumnVisible("status", false));
    act(() => first.result.current.moveColumn("created", -1));

    const second = renderState(store);
    expect(second.result.current.orderedColumns.map((c) => c.id)).toEqual([
      "title",
      "created",
      "status",
    ]);
    expect(second.result.current.visibleColumns.map((c) => c.id)).toEqual(["title", "created"]);
  });

  it("clamps reordering at the edges", () => {
    const { result } = renderState(new InMemoryViewStateRepository());
    act(() => result.current.moveColumn("title", -1));
    expect(result.current.orderedColumns.map((c) => c.id)).toEqual(["title", "status", "created"]);
  });

  it("resets the page index when search or filters change", () => {
    const { result } = renderState(new InMemoryViewStateRepository());
    act(() => result.current.setPagination({ pageIndex: 3, pageSize: 10 }));
    act(() => result.current.setSearch("printer"));
    expect(result.current.pagination.pageIndex).toBe(0);

    act(() => result.current.setPagination({ pageIndex: 2, pageSize: 10 }));
    act(() => result.current.setFilter("status", "open"));
    expect(result.current.pagination.pageIndex).toBe(0);
    expect(result.current.filters).toEqual([{ id: "status", value: "open" }]);
  });

  it("persists search/sorting/filters for client-side views and restores them", () => {
    const store = new InMemoryViewStateRepository();
    const first = renderState(store);
    act(() => first.result.current.setSearch("vpn"));
    act(() => first.result.current.toggleSort("title"));

    const second = renderState(store);
    expect(second.result.current.search).toBe("vpn");
    expect(second.result.current.sorting).toEqual([{ id: "title", desc: false }]);
  });

  it("keeps sorting/filters/search out of persistence for server-side views", () => {
    const store = new InMemoryViewStateRepository();
    const save = vi.spyOn(store, "save");
    const { result } = renderHook(() =>
      useDataViewState<Row>({
        viewId: "v",
        columns: COLUMNS,
        viewStateRepository: store,
        serverSide: true,
        initialPageSize: 10,
      }),
    );
    act(() => result.current.toggleSort("title"));
    act(() => result.current.setColumnVisible("status", false));
    const persisted = save.mock.calls.at(-1)?.[1];
    expect(persisted?.sorting).toEqual([]);
    expect(persisted?.search).toBe("");
  });

  it("delegates query state to a controlled query when provided", () => {
    const onSortingChange = vi.fn();
    const { result } = renderHook(() =>
      useDataViewState<Row>({
        columns: COLUMNS,
        serverSide: true,
        initialPageSize: 10,
        controlledQuery: {
          sorting: [{ id: "status", desc: true }],
          filters: [],
          search: "",
          pagination: { pageIndex: 4, pageSize: 25 },
          onSortingChange,
          onFiltersChange: vi.fn(),
          onSearchChange: vi.fn(),
          onPaginationChange: vi.fn(),
        },
      }),
    );
    expect(result.current.sorting).toEqual([{ id: "status", desc: true }]);
    expect(result.current.pagination).toEqual({ pageIndex: 4, pageSize: 25 });
    act(() => result.current.toggleSort("status"));
    expect(onSortingChange).toHaveBeenCalledWith([]);
  });
});

describe("useServerDataView", () => {
  it("reads its initial state from the URL", () => {
    window.history.replaceState(null, "", "/?page=3&size=25&sort=-title&q=vpn");
    const { result } = renderHook(() => useServerDataView());
    expect(result.current.pagination).toEqual({ pageIndex: 2, pageSize: 25 });
    expect(result.current.sorting).toEqual([{ id: "title", desc: true }]);
    expect(result.current.search).toBe("vpn");
  });

  it("writes state changes back into the URL", () => {
    const { result } = renderHook(() => useServerDataView());
    act(() => result.current.onSearchChange("printer"));
    act(() => result.current.onPaginationChange({ pageIndex: 1, pageSize: 10 }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBe("printer");
    expect(params.get("page")).toBe("2");
  });

  it("prefixes parameters so several views share one page", () => {
    const { result } = renderHook(() => useServerDataView({ paramPrefix: "t" }));
    act(() => result.current.onSearchChange("x"));
    expect(new URLSearchParams(window.location.search).get("t.q")).toBe("x");
  });

  it("ignores a malformed filters parameter", () => {
    window.history.replaceState(null, "", "/?filters=%7Bnot-json");
    const { result } = renderHook(() => useServerDataView());
    expect(result.current.filters).toEqual([]);
  });
});
