import { useCallback, useMemo, useRef, useState } from "react";

import type {
  DataViewColumn,
  DataViewState,
  ViewStateRepository,
} from "../types";
import { emptyDataViewState } from "../types";

export type DataViewSorting = { id: string; desc: boolean }[];
export type DataViewFilters = { id: string; value: unknown }[];
export interface DataViewPaginationState {
  pageIndex: number;
  pageSize: number;
}

/**
 * Externally controlled query state (server-side views): {@link useServerDataView}
 * produces this shape from the URL; passing it makes the hook delegate sorting /
 * filters / search / pagination instead of owning them.
 */
export interface DataViewControlledQuery {
  sorting: DataViewSorting;
  filters: DataViewFilters;
  search: string;
  pagination: DataViewPaginationState;
  onSortingChange: (sorting: DataViewSorting) => void;
  onFiltersChange: (filters: DataViewFilters) => void;
  onSearchChange: (search: string) => void;
  onPaginationChange: (pagination: DataViewPaginationState) => void;
}

export interface UseDataViewStateOptions<T> {
  /** Stable key for persisted preferences; omit to keep preferences in memory only. */
  viewId?: string;
  columns: DataViewColumn<T>[];
  /** Persistence seam; without it (or without a viewId) nothing is persisted. */
  viewStateRepository?: ViewStateRepository;
  /** Server-side views keep sorting/filters/search out of the persisted state. */
  serverSide: boolean;
  initialPageSize: number;
  /** Present for server-side views driven by {@link useServerDataView}. */
  controlledQuery?: DataViewControlledQuery;
}

export interface UseDataViewStateResult<T> {
  sorting: DataViewSorting;
  /** 3-state toggle for one column: asc → desc → none. */
  toggleSort: (columnId: string) => void;
  filters: DataViewFilters;
  setFilter: (columnId: string, value: unknown) => void;
  clearFilters: () => void;
  search: string;
  setSearch: (search: string) => void;
  pagination: DataViewPaginationState;
  setPagination: (pagination: DataViewPaginationState) => void;
  columnVisibility: Record<string, boolean>;
  setColumnVisible: (columnId: string, visible: boolean) => void;
  columnOrder: string[];
  /** Reorder a user column one step (system columns are not part of this order). */
  moveColumn: (columnId: string, direction: -1 | 1) => void;
  columnSizing: Record<string, number>;
  /** Commit resized widths (called once per drag, on pointer-up). */
  commitColumnSizing: (sizing: Record<string, number>) => void;
  /** The user columns in effective order (persisted order first, new columns appended). */
  orderedColumns: DataViewColumn<T>[];
  /** The ordered columns that are currently visible. */
  visibleColumns: DataViewColumn<T>[];
}

function orderColumns<T>(columns: DataViewColumn<T>[], order: string[]): DataViewColumn<T>[] {
  if (order.length === 0) {
    return columns;
  }
  const byId = new Map(columns.map((column) => [column.id, column]));
  const ordered: DataViewColumn<T>[] = [];
  for (const id of order) {
    const column = byId.get(id);
    if (column !== undefined) {
      ordered.push(column);
      byId.delete(id);
    }
  }
  // Columns added after the order was persisted keep their declared position at the end.
  ordered.push(...byId.values());
  return ordered;
}

/**
 * The headless state engine behind {@link DataView}: view preferences (column
 * visibility / order / sizing) always live here and persist through the
 * {@link ViewStateRepository}; the query state (sorting / filters / search /
 * pagination) is owned here for client-side views and delegated to
 * `controlledQuery` for server-side ones.
 */
export function useDataViewState<T>({
  viewId,
  columns,
  viewStateRepository,
  serverSide,
  initialPageSize,
  controlledQuery,
}: UseDataViewStateOptions<T>): UseDataViewStateResult<T> {
  // Load persisted state exactly once (lazy initializer); corrupt data already fell
  // back to `undefined` inside the repository.
  const [persisted] = useState<DataViewState | undefined>(() =>
    viewId !== undefined && viewStateRepository !== undefined
      ? viewStateRepository.load(viewId)
      : undefined,
  );

  const [ownSorting, setOwnSorting] = useState<DataViewSorting>(
    serverSide ? [] : (persisted?.sorting ?? []),
  );
  const [ownFilters, setOwnFilters] = useState<DataViewFilters>(
    serverSide ? [] : (persisted?.filters ?? []),
  );
  const [ownSearch, setOwnSearch] = useState<string>(serverSide ? "" : (persisted?.search ?? ""));
  const [ownPagination, setOwnPagination] = useState<DataViewPaginationState>({
    pageIndex: 0,
    pageSize: initialPageSize,
  });
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(
    persisted?.columnVisibility ?? {},
  );
  const [columnOrder, setColumnOrder] = useState<string[]>(persisted?.columnOrder ?? []);
  const [columnSizing, setColumnSizing] = useState<Record<string, number>>(
    persisted?.columnSizing ?? {},
  );

  const sorting = controlledQuery?.sorting ?? ownSorting;
  const filters = controlledQuery?.filters ?? ownFilters;
  const search = controlledQuery?.search ?? ownSearch;
  const pagination = controlledQuery?.pagination ?? ownPagination;

  // Persist through a ref-held snapshot so the callbacks below stay stable and each
  // save writes the full, current state.
  const stateRef = useRef<DataViewState>(emptyDataViewState());
  stateRef.current = {
    columnVisibility,
    columnOrder,
    columnSizing,
    sorting: serverSide ? [] : sorting,
    filters: serverSide ? [] : filters,
    search: serverSide ? "" : search,
  };
  const persistRef = useRef<(patch: Partial<DataViewState>) => void>(() => undefined);
  persistRef.current = (patch) => {
    if (viewId !== undefined && viewStateRepository !== undefined) {
      viewStateRepository.save(viewId, { ...stateRef.current, ...patch });
    }
  };

  const controlledRef = useRef(controlledQuery);
  controlledRef.current = controlledQuery;
  const queryRef = useRef({ sorting, filters, search, pagination });
  queryRef.current = { sorting, filters, search, pagination };

  const setSorting = useCallback(
    (next: DataViewSorting) => {
      if (controlledRef.current !== undefined) {
        controlledRef.current.onSortingChange(next);
        return;
      }
      setOwnSorting(next);
      if (!serverSide) {
        persistRef.current({ sorting: next });
      }
    },
    [serverSide],
  );

  const toggleSort = useCallback(
    (columnId: string) => {
      const current = queryRef.current.sorting.find((sort) => sort.id === columnId);
      const next: DataViewSorting =
        current === undefined
          ? [{ id: columnId, desc: false }]
          : current.desc
            ? []
            : [{ id: columnId, desc: true }];
      setSorting(next);
    },
    [setSorting],
  );

  const setPagination = useCallback((next: DataViewPaginationState) => {
    if (controlledRef.current !== undefined) {
      controlledRef.current.onPaginationChange(next);
    } else {
      setOwnPagination(next);
    }
  }, []);

  const setFilters = useCallback(
    (next: DataViewFilters) => {
      if (controlledRef.current !== undefined) {
        controlledRef.current.onFiltersChange(next);
      } else {
        setOwnFilters(next);
        if (!serverSide) {
          persistRef.current({ filters: next });
        }
      }
      // A changed filter invalidates the current page position.
      setPagination({ ...queryRef.current.pagination, pageIndex: 0 });
    },
    [serverSide, setPagination],
  );

  const setFilter = useCallback(
    (columnId: string, value: unknown) => {
      const rest = queryRef.current.filters.filter((filter) => filter.id !== columnId);
      const cleared =
        value === undefined || value === null || value === "" ||
        (Array.isArray(value) && value.length === 0);
      setFilters(cleared ? rest : [...rest, { id: columnId, value }]);
    },
    [setFilters],
  );

  const clearFilters = useCallback(() => {
    setFilters([]);
  }, [setFilters]);

  const setSearch = useCallback(
    (next: string) => {
      if (controlledRef.current !== undefined) {
        controlledRef.current.onSearchChange(next);
      } else {
        setOwnSearch(next);
        if (!serverSide) {
          persistRef.current({ search: next });
        }
      }
      setPagination({ ...queryRef.current.pagination, pageIndex: 0 });
    },
    [serverSide, setPagination],
  );

  const setColumnVisible = useCallback((columnId: string, visible: boolean) => {
    setColumnVisibility((current) => {
      const next = { ...current, [columnId]: visible };
      persistRef.current({ columnVisibility: next });
      return next;
    });
  }, []);

  const columnIds = useMemo(() => columns.map((column) => column.id), [columns]);

  const moveColumn = useCallback(
    (columnId: string, direction: -1 | 1) => {
      setColumnOrder((current) => {
        const effective = current.length > 0 ? [...current] : [...columnIds];
        // Only known user columns take part; stale persisted ids are dropped.
        const order = effective.filter((id) => columnIds.includes(id));
        for (const id of columnIds) {
          if (!order.includes(id)) {
            order.push(id);
          }
        }
        const from = order.indexOf(columnId);
        const to = from + direction;
        if (from === -1 || to < 0 || to >= order.length) {
          return current;
        }
        const next = [...order];
        next.splice(from, 1);
        next.splice(to, 0, columnId);
        persistRef.current({ columnOrder: next });
        return next;
      });
    },
    [columnIds],
  );

  const commitColumnSizing = useCallback((sizing: Record<string, number>) => {
    setColumnSizing((current) => {
      const next = { ...current, ...sizing };
      persistRef.current({ columnSizing: next });
      return next;
    });
  }, []);

  const orderedColumns = useMemo(() => orderColumns(columns, columnOrder), [columns, columnOrder]);
  const visibleColumns = useMemo(
    () => orderedColumns.filter((column) => columnVisibility[column.id] !== false),
    [orderedColumns, columnVisibility],
  );

  return {
    sorting,
    toggleSort,
    filters,
    setFilter,
    clearFilters,
    search,
    setSearch,
    pagination,
    setPagination,
    columnVisibility,
    setColumnVisible,
    columnOrder,
    moveColumn,
    columnSizing,
    commitColumnSizing,
    orderedColumns,
    visibleColumns,
  };
}
