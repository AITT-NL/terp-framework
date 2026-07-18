import type { ReactNode } from "react";

import type { UiText } from "../uiText";

/**
 * Query descriptor the DataView emits — the only contract with the data layer.
 * A {@link DataViewRepository} receives this and returns one {@link DataViewResult} page;
 * the component never fetches or filters on its own.
 */
export interface DataViewQuery {
  pagination: { pageIndex: number; pageSize: number };
  sorting: { id: string; desc: boolean }[];
  filters: { id: string; value: unknown }[];
  search: string;
  /** Broadened search scope active (e.g. include archived/closed records). */
  searchBroadened: boolean;
}

/** Uniform page result every repository returns. */
export interface DataViewResult<T> {
  rows: T[];
  totalCount: number;
}

/**
 * The repository abstraction. DataView only ever talks to this — swapping in-memory ↔ HTTP
 * data requires zero changes to any component file (dependency inversion / open-closed).
 *
 * @example
 * ```ts
 * const repo = new InMemoryDataViewRepository(tickets, {
 *   getRowId: (t) => t.id,
 *   searchFields: ["title", "assignee"],
 * });
 * <DataView repository={repo} columns={columns} />
 * ```
 */
export interface DataViewRepository<T> {
  query(q: DataViewQuery, signal?: AbortSignal): Promise<DataViewResult<T>>;
  /** Stable row identity — selection/expansion must survive re-sorts and refetches. */
  getRowId(row: T): string;
  /** Capability flags let the component adapt (e.g. hide the search box). */
  capabilities: {
    /** true → manual sorting/filtering/pagination; the repo does the work per query. */
    serverSide: boolean;
    search: boolean;
    /** Supports the "search everything" broadened toggle. */
    searchScope: boolean;
  };
  /**
   * Optional facet support: the distinct values of one column across the full data set
   * (client-side repositories can provide it cheaply; server-side ones may omit it).
   */
  getFacetedValues?(columnId: string): unknown[];
}

/** Everything the user customises about a view, persisted per stable `viewId`. */
export interface DataViewState {
  columnVisibility: Record<string, boolean>;
  columnOrder: string[];
  /** User-resized widths in px. */
  columnSizing: Record<string, number>;
  /** Client-side views only. */
  sorting: { id: string; desc: boolean }[];
  /** Client-side views only. */
  filters: { id: string; value: unknown }[];
  search: string;
}

/**
 * Where a user's view customisations live. DataView never touches `localStorage`
 * directly — it loads/saves through this seam, so preferences can move to any store
 * (server-backed, in-memory for tests) without touching a component file.
 */
export interface ViewStateRepository {
  load(viewId: string): DataViewState | undefined;
  save(viewId: string, state: DataViewState): void;
}

/** An empty {@link DataViewState} — the fallback when nothing was persisted yet. */
export function emptyDataViewState(): DataViewState {
  return {
    columnVisibility: {},
    columnOrder: [],
    columnSizing: {},
    sorting: [],
    filters: [],
    search: "",
  };
}

/** Slot a column occupies in the responsive card layout. */
export type DataViewMobileSlot = "title" | "subtitle" | "status" | "date";

/** Typed column meta the DataView-specific features read. */
export interface DataViewColumnMeta {
  /** Human-readable name used in the column-settings menu (falls back to the header). */
  label?: UiText;
  /** Slot in the auto-composed card layout. */
  mobileSlot?: DataViewMobileSlot;
  /** Fixed width hint (number = px, or any CSS length). */
  width?: number | string;
}

/** Generic, typed column definition for {@link DataView}. */
export interface DataViewColumn<T> {
  /** Stable id — used for sorting/filter ids, visibility, ordering and sizing. */
  id: string;
  /** Header content. */
  header: UiText;
  /** The raw value of this column for a row (used by default cell rendering). */
  accessor?: (row: T) => unknown;
  /** Custom cell renderer; defaults to `String(accessor(row))`. */
  cell?: (row: T) => ReactNode;
  /** Whether the header offers the 3-state sort toggle (default true). */
  enableSorting?: boolean;
  meta?: DataViewColumnMeta;
}

/** A per-row action rendered by {@link DataView}'s actions column (or in card view). */
export interface DataViewRowAction<T> {
  label: UiText;
  icon?: ReactNode;
  onClick?: (row: T) => void;
  variant?: "default" | "destructive";
  /** Boolean or predicate of the row. */
  disabled?: boolean | ((row: T) => boolean);
  /** Boolean or predicate of the row. */
  hidden?: boolean | ((row: T) => boolean);
  /** Render beside the ellipsis menu in "menu" layout. */
  inline?: boolean;
  /**
   * Fully custom control; custom controls always render inline and own their
   * interaction surface (DataView only stops row-click propagation around them).
   */
  render?: (row: T) => ReactNode;
}

/** A batch action shown in the selection toolbar. */
export interface DataViewBatchAction<T> {
  label: UiText;
  icon?: ReactNode;
  onClick: (rows: T[]) => void;
  /**
   * Invoked instead of `onClick` when select-all-across-pages mode is active
   * (the current page's rows are still passed for context).
   */
  onSelectAll?: (rows: T[]) => void;
  variant?: "default" | "destructive";
  /** Render as a button in the toolbar; otherwise it goes into the overflow menu. */
  inline?: boolean;
}

/** Caller-owned wiring of the broadened "search everything" toggle. */
export interface DataViewSearchScope {
  broadened: boolean;
  onBroadenedChange: (broadened: boolean) => void;
  /** Button label while the scope is narrow (e.g. "Search everything"). */
  label: UiText;
  /** Button label while the scope is broadened (e.g. "Searching everything"). */
  broadenedLabel: UiText;
}

/** Every user-facing string the DataView renders, overridable per instance. */
export interface DataViewStrings {
  searchPlaceholder: UiText;
  clearSearch: UiText;
  clearFilters: UiText;
  viewOptions: UiText;
  columns: UiText;
  moveUp: UiText;
  moveDown: UiText;
  tableView: UiText;
  cardView: UiText;
  pageSize: UiText;
  resultsRange: UiText; // "{from}–{to} of {total} results"
  pageOf: UiText; // "Page {page} of {pages}"
  firstPage: UiText;
  previousPage: UiText;
  nextPage: UiText;
  lastPage: UiText;
  selectAllPage: UiText;
  selectRow: UiText;
  selected: UiText; // "{count} selected"
  selectAllResults: UiText; // "Select all {total} results"
  clearSelection: UiText;
  moreActions: UiText;
  actions: UiText;
  openRow: UiText; // "Open details: {label}"
  expandRow: UiText;
  collapseRow: UiText;
  empty: UiText;
  loading: UiText;
  refreshing: UiText;
  errorTitle: UiText;
  resizeColumn: UiText;
}

export const DEFAULT_DATA_VIEW_STRINGS: DataViewStrings = {
  searchPlaceholder: "Search…",
  clearSearch: "Clear search",
  clearFilters: "Clear filters",
  viewOptions: "View options",
  columns: "Columns",
  moveUp: "Move up",
  moveDown: "Move down",
  tableView: "Table view",
  cardView: "Card view",
  pageSize: "Rows per page",
  resultsRange: "{from}–{to} of {total} results",
  pageOf: "Page {page} of {pages}",
  firstPage: "First page",
  previousPage: "Previous page",
  nextPage: "Next page",
  lastPage: "Last page",
  selectAllPage: "Select all rows on this page",
  selectRow: "Select row",
  selected: "{count} selected",
  selectAllResults: "Select all {total} results",
  clearSelection: "Clear selection",
  moreActions: "More actions",
  actions: "Actions",
  openRow: "Open details: {label}",
  expandRow: "Expand row",
  collapseRow: "Collapse row",
  empty: "Nothing to show.",
  loading: "Loading…",
  refreshing: "Refreshing…",
  errorTitle: "Could not load data.",
  resizeColumn: "Resize column",
};

/** Tiny `{placeholder}` formatter for the countable strings above. */
export function formatDataViewString(
  template: string,
  values: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}

/** Resolve a row-action boolean-or-predicate flag against a row. */
export function resolveRowFlag<T>(
  flag: boolean | ((row: T) => boolean) | undefined,
  row: T,
): boolean {
  return typeof flag === "function" ? flag(row) : flag === true;
}
