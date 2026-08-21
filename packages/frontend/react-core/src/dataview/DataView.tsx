import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { NARROW_VIEWPORT } from "../breakpoints";
import { EmptyState } from "../EmptyState";
import { ErrorState } from "../ErrorState";
import type { BadgeTone } from "../ui/Badge";
import type { UiText } from "../uiText";
import { DataViewCardList } from "./DataViewCardList";
import { DataViewPagination } from "./DataViewPagination";
import type { DataViewRowActionsLayout } from "./DataViewRowActions";
import { DataViewTable } from "./DataViewTable";
import { DataViewToolbar } from "./DataViewToolbar";
import { useDataViewQuery } from "./hooks/useDataViewQuery";
import { useDataViewState } from "./hooks/useDataViewState";
import type { DataViewControlledQuery } from "./hooks/useDataViewState";
import { DataViewTextProvider, useDataViewText } from "./internal";
import type {
  DataViewBatchAction,
  DataViewColumn,
  DataViewDensity,
  DataViewQuery,
  DataViewRepository,
  DataViewRowAction,
  DataViewSearchScope,
  DataViewStrings,
  ViewStateRepository,
} from "./types";

/** Embedded views render all rows; the parent owns paging. */
const EMBEDDED_PAGE_SIZE = 10_000;

interface DataViewBaseProps<T> {
  /** Stable key for persisted view preferences; omit to keep them in memory only. */
  viewId?: string;
  /** The data access seam — DataView never fetches on its own. */
  repository: DataViewRepository<T>;
  /** The preference persistence seam (e.g. `LocalStorageViewStateRepository`). */
  viewStateRepository?: ViewStateRepository;
  columns: DataViewColumn<T>[];
  /** "embedded" renders a plain compact view: no view toggle, no page-size selector, no footer. */
  variant?: "full" | "embedded";
  /**
   * How tightly this view packs its cells and controls (default `"comfortable"`).
   *
   * `"compact"` stamps `data-density="compact"` on the root, which re-scopes the live
   * density tokens for the whole subtree — cell padding here, and the control heights
   * `Button`, `Input` and `Select` already read, so the toolbar tightens with the table.
   *
   * `"comfortable"` stamps NO attribute, because comfortable IS the token sheet's
   * `:root` value and an attribute for it would match no rule. The consequence worth
   * (Historic note, since the prop's behaviour changed: `"comfortable"` used to stamp
   * nothing, on the grounds that comfortable was the sheet's own `:root` value — which was
   * true until the shell could make an ancestor compact. Both values are stamped now, and
   * both have a rule. Where nothing above is compact the two compute identically, so the
   * change is zero-diff by construction.)
   *
   * What used to be worth knowing: inside an already-compact subtree, `density="comfortable"`
   * did not make
   * this view comfortable again. Expressing that needs a named comfortable copy of
   * each live token, which ADR 0094 defers until something asks — nothing can ask
   * until the shell takes a density of its own.
   */
  density?: DataViewDensity;
  enableSelection?: boolean;
  batchActions?: DataViewBatchAction<T>[];
  rowActions?: (row: T) => DataViewRowAction<T>[];
  rowActionsLayout?: DataViewRowActionsLayout;
  searchPlaceholder?: UiText;
  searchDebounceMs?: number;
  /** Caller-owned "search everything" toggle (see {@link DataViewSearchScope}). */
  searchScope?: DataViewSearchScope;
  pageSizeOptions?: number[];
  initialPageSize?: number;
  renderExpanded?: (row: T) => ReactNode;
  /**
   * Row-level status tone: the *row* is in that state (a refused link, a failed run),
   * not one of its cells — the right altitude for a validation-driven table, where a
   * Badge cell would misattribute the verdict to a column. Tints the row/card with the
   * tone's soft token (the same one `Badge` uses) and stamps `data-tone` on it;
   * `null`/`undefined` leaves the row untinted.
   */
  getRowTone?: (row: T) => BadgeTone | null;
  /** Fully custom cards in the responsive card layout. */
  renderCard?: (row: T) => ReactNode;
  /** Custom filter controls, rendered in the toolbar. */
  toolbarContent?: ReactNode;
  /** Trailing toolbar slot (e.g. a "New" button). */
  toolbarTrailing?: ReactNode;
  /** Rendered inside the empty state (e.g. a "clear filters" button). */
  emptyActions?: ReactNode;
  emptyMessage?: UiText;
  /** Custom error state; defaults to {@link ErrorState}. */
  renderError?: (error: unknown) => ReactNode;
  /** Shows the toolbar "clear filters" action and wires it to this reset. */
  onClearFilters?: () => void;
  /** URL-backed query state for server-side views (from {@link useServerDataView}). */
  serverQuery?: DataViewControlledQuery;
  /** Per-instance overrides of the DataView's user-facing strings. */
  strings?: Partial<DataViewStrings>;
}

export type DataViewProps<T> = DataViewBaseProps<T> & (
  | {
      onRowClick?: undefined;
      getRowLabel?: undefined;
    }
  | {
      /** Pointer activation for overview-to-detail navigation. */
      onRowClick: (row: T) => void;
      /** Accessible record name used by the row's native activation button. */
      getRowLabel: (row: T) => UiText;
    }
);

/**
 * The single sanctioned surface for rendering data collections: a repository-driven
 * table/card view with search, sorting, pagination, column management, selection,
 * batch actions, row actions, expandable rows and persisted view preferences.
 *
 * DataView never fetches and never touches `localStorage`: all data access goes
 * through the {@link DataViewRepository} and all preference persistence through the
 * {@link ViewStateRepository} — swapping either implementation requires zero changes
 * to any component file.
 */
export function DataView<T>(props: DataViewProps<T>) {
  return (
    <DataViewTextProvider overrides={props.strings}>
      <DataViewInner {...props} />
    </DataViewTextProvider>
  );
}

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(NARROW_VIEWPORT).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(NARROW_VIEWPORT);
    const onChange = () => setIsMobile(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}

function DataViewInner<T>(props: DataViewProps<T>) {
  const { strings, resolve } = useDataViewText();
  const embedded = props.variant === "embedded";
  // Only the compact value is expressible as an attribute; see the prop's doc comment.
  const densityAttribute = props.density;
  // Hoisted rather than written inline at the two roots, which is what the density
  // attribute above already does and what keeps the marker scanner out of a trap: it
  // reads a whole expression container, so every string literal inside one counts as a
  // marker name and a conditional written at the attribute would report phantoms.
  const variantAttribute = embedded ? "embedded" : "full";
  const serverSide = props.repository.capabilities.serverSide;
  const initialPageSize = embedded
    ? EMBEDDED_PAGE_SIZE
    : (props.initialPageSize ?? props.pageSizeOptions?.[0] ?? 10);

  const state = useDataViewState<T>({
    viewId: props.viewId,
    columns: props.columns,
    viewStateRepository: props.viewStateRepository,
    serverSide,
    initialPageSize,
    controlledQuery: props.serverQuery,
  });

  const query: DataViewQuery = useMemo(
    () => ({
      pagination: state.pagination,
      sorting: state.sorting,
      filters: state.filters,
      search: state.search,
      searchBroadened: props.searchScope?.broadened ?? false,
    }),
    [state.pagination, state.sorting, state.filters, state.search, props.searchScope?.broadened],
  );

  const { rows, totalCount, isLoading, isFetching, error } = useDataViewQuery(
    props.repository,
    query,
  );

  // An out-of-range page (stale deep link, shrunk result set) snaps back to the
  // last valid page, so the emitted query and the footer never disagree.
  const setPagination = state.setPagination;
  useEffect(() => {
    if (isLoading || isFetching || (error !== null && error !== undefined)) {
      return;
    }
    const { pageIndex, pageSize } = query.pagination;
    const lastPageIndex = Math.max(0, Math.ceil(totalCount / pageSize) - 1);
    if (pageIndex > lastPageIndex) {
      setPagination({ pageIndex: lastPageIndex, pageSize });
    }
  }, [isLoading, isFetching, error, totalCount, query.pagination, setPagination]);

  // ----- selection (keyed by getRowId so it survives re-sorts and refetches) -----
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const [selectAllAcrossPages, setSelectAllAcrossPages] = useState(false);
  // Row objects for every id ever selected, so batch actions receive rows even after paging.
  const selectedRowsRef = useRef(new Map<string, T>());

  const getRowId = useCallback(
    (row: T) => props.repository.getRowId(row),
    [props.repository],
  );
  const pageRowIds = useMemo(() => rows.map(getRowId), [rows, getRowId]);
  const allPageSelected = pageRowIds.length > 0 && pageRowIds.every((id) => selectedIds.has(id));
  const somePageSelected = pageRowIds.some((id) => selectedIds.has(id));

  const toggleSelected = useCallback(
    (rowId: string) => {
      setSelectedIds((current) => {
        const next = new Set(current);
        if (next.has(rowId)) {
          next.delete(rowId);
          selectedRowsRef.current.delete(rowId);
          // Breaking the page selection always exits select-all-across-pages mode.
          setSelectAllAcrossPages(false);
        } else {
          next.add(rowId);
          const row = rows.find((candidate) => getRowId(candidate) === rowId);
          if (row !== undefined) {
            selectedRowsRef.current.set(rowId, row);
          }
        }
        return next;
      });
    },
    [rows, getRowId],
  );

  const toggleSelectPage = useCallback(() => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (pageRowIds.length > 0 && pageRowIds.every((id) => next.has(id))) {
        for (const id of pageRowIds) {
          next.delete(id);
          selectedRowsRef.current.delete(id);
        }
        setSelectAllAcrossPages(false);
      } else {
        for (const row of rows) {
          const id = getRowId(row);
          next.add(id);
          selectedRowsRef.current.set(id, row);
        }
      }
      return next;
    });
  }, [pageRowIds, rows, getRowId]);

  const clearSelection = useCallback(() => {
    setSelectedIds((current) => (current.size === 0 ? current : new Set()));
    setSelectAllAcrossPages(false);
    selectedRowsRef.current.clear();
  }, []);

  // Changing what the result set *is* (filters, search, scope) invalidates the
  // selection: "select all N results" must never carry over to a different query,
  // or batch onSelectAll would act on records the user never confirmed.
  const selectionScopeKey = JSON.stringify({
    filters: query.filters,
    search: query.search,
    broadened: query.searchBroadened,
  });
  useEffect(() => {
    clearSelection();
  }, [selectionScopeKey, clearSelection]);

  const onBatchAction = useCallback(
    (action: DataViewBatchAction<T>) => {
      const selectedRows = [...selectedIds]
        .map((id) => selectedRowsRef.current.get(id))
        .filter((row): row is T => row !== undefined);
      if (selectAllAcrossPages && action.onSelectAll !== undefined) {
        action.onSelectAll(selectedRows);
      } else {
        action.onClick(selectedRows);
      }
    },
    [selectedIds, selectAllAcrossPages],
  );

  // ----- expansion (keyed by row id) -----
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set());
  const toggleExpanded = useCallback((rowId: string) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(rowId)) {
        next.delete(rowId);
      } else {
        next.add(rowId);
      }
      return next;
    });
  }, []);

  // ----- responsive layout: auto until the user toggles, manual choice wins -----
  const isMobile = useIsMobile();
  const [manualLayout, setManualLayout] = useState<"table" | "cards" | null>(null);
  const layout: "table" | "cards" = manualLayout ?? (isMobile ? "cards" : "table");

  const hasActiveFilters = state.filters.length > 0 || state.search !== "";
  const clearFilters = () => {
    state.clearFilters();
    state.setSearch("");
    props.onClearFilters?.();
  };

  const content = (() => {
    if (isLoading) {
      return <DataViewSkeleton label={resolve(strings.loading)} />;
    }
    if (error !== null && error !== undefined) {
      return props.renderError !== undefined ? (
        <>{props.renderError(error)}</>
      ) : (
        <div data-terp="dataview-error">
          <ErrorState title={strings.errorTitle} error={error} />
        </div>
      );
    }
    if (rows.length === 0) {
      return <EmptyState title={props.emptyMessage ?? strings.empty} action={props.emptyActions} />;
    }
    if (layout === "cards") {
      return (
        <DataViewCardList
          rows={rows}
          columns={state.orderedColumns}
          getRowId={getRowId}
          onRowClick={props.onRowClick}
          getRowLabel={props.getRowLabel}
          getRowTone={props.getRowTone}
          renderCard={props.renderCard}
          selectionEnabled={props.enableSelection === true}
          isSelected={(id) => selectedIds.has(id)}
          onToggleSelected={toggleSelected}
          renderExpanded={props.renderExpanded}
          isExpanded={(id) => expandedIds.has(id)}
          onToggleExpanded={toggleExpanded}
          rowActions={props.rowActions}
        />
      );
    }
    return (
      <div data-terp="dataview-scroll">
        <DataViewTable
          rows={rows}
          columns={state.visibleColumns}
          getRowId={getRowId}
          onRowClick={props.onRowClick}
          getRowLabel={props.getRowLabel}
          getRowTone={props.getRowTone}
          isMobile={isMobile}
          sorting={state.sorting}
          onToggleSort={state.toggleSort}
          columnSizing={state.columnSizing}
          onCommitColumnSizing={state.commitColumnSizing}
          selectionEnabled={props.enableSelection === true}
          isSelected={(id) => selectedIds.has(id)}
          onToggleSelected={toggleSelected}
          allPageSelected={allPageSelected}
          somePageSelected={somePageSelected}
          onToggleSelectPage={toggleSelectPage}
          renderExpanded={props.renderExpanded}
          isExpanded={(id) => expandedIds.has(id)}
          onToggleExpanded={toggleExpanded}
          rowActions={props.rowActions}
          rowActionsLayout={props.rowActionsLayout ?? "menu"}
        />
      </div>
    );
  })();

  if (embedded) {
    // Stable inputs only: keying this on transient fetch state would pop the
    // whole band in and out on mount and on every background refetch.
    const showsEmbeddedToolbar =
      props.repository.capabilities.search ||
      props.searchScope !== undefined ||
      props.onClearFilters !== undefined ||
      props.enableSelection === true ||
      (props.batchActions?.length ?? 0) > 0 ||
      props.toolbarContent !== undefined ||
      props.toolbarTrailing !== undefined;
    return (
      <div data-terp="dataview" data-variant={variantAttribute} data-density={densityAttribute}>
        {showsEmbeddedToolbar && (
          <DataViewToolbar<T>
            searchEnabled={props.repository.capabilities.search}
            search={state.search}
            onSearchChange={state.setSearch}
            searchPlaceholder={props.searchPlaceholder}
            searchDebounceMs={props.searchDebounceMs}
            searchScope={props.repository.capabilities.searchScope ? props.searchScope : undefined}
            onClearFilters={props.onClearFilters !== undefined ? clearFilters : undefined}
            hasActiveFilters={hasActiveFilters}
            layout={layout}
            selectedCount={selectedIds.size}
            totalCount={totalCount}
            selectAllAcrossPages={selectAllAcrossPages}
            onSelectAllAcrossPages={
              allPageSelected && totalCount > selectedIds.size
                ? () => setSelectAllAcrossPages(true)
                : undefined
            }
            onClearSelection={clearSelection}
            batchActions={props.batchActions}
            onBatchAction={onBatchAction}
            isFetching={isFetching}
            trailing={props.toolbarTrailing}
          >
            {props.toolbarContent}
          </DataViewToolbar>
        )}
        {content}
      </div>
    );
  }

  return (
    <div data-terp="dataview" data-variant={variantAttribute} data-density={densityAttribute}>
      <DataViewToolbar<T>
        searchEnabled={props.repository.capabilities.search}
        search={state.search}
        onSearchChange={state.setSearch}
        searchPlaceholder={props.searchPlaceholder}
        searchDebounceMs={props.searchDebounceMs}
        searchScope={props.repository.capabilities.searchScope ? props.searchScope : undefined}
        onClearFilters={props.onClearFilters !== undefined ? clearFilters : undefined}
        hasActiveFilters={hasActiveFilters}
        columnSettings={{
          columns: state.orderedColumns,
          columnVisibility: state.columnVisibility,
          onColumnVisibleChange: state.setColumnVisible,
          onMoveColumn: state.moveColumn,
        }}
        layout={layout}
        onLayoutChange={setManualLayout}
        pageSize={state.pagination.pageSize}
        pageSizeOptions={props.pageSizeOptions}
        onPageSizeChange={(pageSize) =>
          state.setPagination({ pageIndex: 0, pageSize })
        }
        selectedCount={selectedIds.size}
        totalCount={totalCount}
        selectAllAcrossPages={selectAllAcrossPages}
        onSelectAllAcrossPages={
          allPageSelected && totalCount > selectedIds.size
            ? () => setSelectAllAcrossPages(true)
            : undefined
        }
        onClearSelection={clearSelection}
        batchActions={props.batchActions}
        onBatchAction={onBatchAction}
        isFetching={isFetching}
        trailing={props.toolbarTrailing}
      >
        {props.toolbarContent}
      </DataViewToolbar>
      {content}
      <DataViewPagination
        pagination={state.pagination}
        totalCount={totalCount}
        onPaginationChange={state.setPagination}
      />
    </div>
  );
}

/**
 * Fixed-height placeholder rows so the initial load never causes a layout jump.
 *
 * One consequence of taking those heights from the sheet is worth stating where it
 * bites, because it is the sharpest instance of something the whole migration accepted
 * rather than anything peculiar to this component: the style injector is guarded on
 * `document`, so no migrated rule reaches server-rendered HTML. A server-rendered
 * DataView emits its toolbar and this skeleton and nothing else, which makes this the
 * one place where "no layout jump" is the entire reason the markup exists. Until
 * hydration these five divs are now zero-height. `ssr.test.tsx` asserts the marker
 * string only, so nothing fails — it is a trade, recorded, not an oversight.
 */
function DataViewSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} data-terp="dataview-skeleton">
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} aria-hidden />
      ))}
    </div>
  );
}
