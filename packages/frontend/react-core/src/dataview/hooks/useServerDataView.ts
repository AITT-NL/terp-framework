import { useCallback, useEffect, useState } from "react";

import type {
  DataViewControlledQuery,
  DataViewFilters,
  DataViewPaginationState,
  DataViewSorting,
} from "./useDataViewState";

export interface UseServerDataViewOptions {
  /** Prefix for the URL parameters, so several views can share one page. */
  paramPrefix?: string;
  initialPageSize?: number;
}

interface UrlQueryState {
  sorting: DataViewSorting;
  filters: DataViewFilters;
  search: string;
  pagination: DataViewPaginationState;
}

function readUrlState(prefix: string, initialPageSize: number): UrlQueryState {
  const params = new URLSearchParams(window.location.search);
  const read = (key: string) => params.get(prefix === "" ? key : `${prefix}.${key}`);

  const page = Number(read("page") ?? "1");
  const size = Number(read("size") ?? String(initialPageSize));
  const sorting: DataViewSorting = (read("sort") ?? "")
    .split(",")
    .filter((entry) => entry !== "")
    .map((entry) =>
      entry.startsWith("-") ? { id: entry.slice(1), desc: true } : { id: entry, desc: false },
    );

  let filters: DataViewFilters = [];
  const rawFilters = read("filters");
  if (rawFilters !== null) {
    try {
      const parsed: unknown = JSON.parse(rawFilters);
      if (Array.isArray(parsed)) {
        filters = parsed.filter(
          (entry): entry is { id: string; value: unknown } =>
            typeof entry === "object" && entry !== null && typeof (entry as { id?: unknown }).id === "string",
        );
      }
    } catch {
      // A malformed filters param falls back to no filters.
    }
  }

  return {
    sorting,
    filters,
    search: read("q") ?? "",
    pagination: {
      pageIndex: Number.isFinite(page) && page >= 1 ? page - 1 : 0,
      pageSize: Number.isFinite(size) && size > 0 ? size : initialPageSize,
    },
  };
}

function writeUrlState(prefix: string, state: UrlQueryState, initialPageSize: number): void {
  const params = new URLSearchParams(window.location.search);
  const set = (key: string, value: string | undefined) => {
    const name = prefix === "" ? key : `${prefix}.${key}`;
    if (value === undefined) {
      params.delete(name);
    } else {
      params.set(name, value);
    }
  };

  set("page", state.pagination.pageIndex > 0 ? String(state.pagination.pageIndex + 1) : undefined);
  set(
    "size",
    state.pagination.pageSize !== initialPageSize ? String(state.pagination.pageSize) : undefined,
  );
  set(
    "sort",
    state.sorting.length > 0
      ? state.sorting.map((sort) => (sort.desc ? `-${sort.id}` : sort.id)).join(",")
      : undefined,
  );
  set("filters", state.filters.length > 0 ? JSON.stringify(state.filters) : undefined);
  set("q", state.search !== "" ? state.search : undefined);

  const query = params.toString();
  const url = `${window.location.pathname}${query === "" ? "" : `?${query}`}${window.location.hash}`;
  window.history.replaceState(window.history.state, "", url);
}

/**
 * Query state for **server-side** views, kept in the URL (page, size, sort, filters,
 * search) so a view survives reloads and can be deep-linked — the server-side analog
 * of the client-side persistence a {@link ViewStateRepository} provides.
 *
 * @example
 * ```tsx
 * const server = useServerDataView({ initialPageSize: 25 });
 * <DataView repository={httpRepo} columns={columns} serverQuery={server} />
 * ```
 */
export function useServerDataView({
  paramPrefix = "",
  initialPageSize = 10,
}: UseServerDataViewOptions = {}): DataViewControlledQuery {
  const [state, setState] = useState<UrlQueryState>(() =>
    readUrlState(paramPrefix, initialPageSize),
  );

  // Re-read on history navigation so back/forward restores the view.
  useEffect(() => {
    const onPopState = () => setState(readUrlState(paramPrefix, initialPageSize));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [paramPrefix, initialPageSize]);

  const update = useCallback(
    (patch: Partial<UrlQueryState>) => {
      setState((current) => {
        const next = { ...current, ...patch };
        writeUrlState(paramPrefix, next, initialPageSize);
        return next;
      });
    },
    [paramPrefix, initialPageSize],
  );

  const onSortingChange = useCallback(
    (sorting: DataViewSorting) => update({ sorting }),
    [update],
  );
  const onFiltersChange = useCallback(
    (filters: DataViewFilters) => update({ filters }),
    [update],
  );
  const onSearchChange = useCallback((search: string) => update({ search }), [update]);
  const onPaginationChange = useCallback(
    (pagination: DataViewPaginationState) => update({ pagination }),
    [update],
  );

  return {
    sorting: state.sorting,
    filters: state.filters,
    search: state.search,
    pagination: state.pagination,
    onSortingChange,
    onFiltersChange,
    onSearchChange,
    onPaginationChange,
  };
}
