import type { ReactNode } from "react";

import type { BadgeTone } from "../ui/Badge";
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
 *   // Annotating the field parameter makes searchFields compile-checked.
 *   getValue: (t, col: keyof Ticket & string) => t[col],
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

/**
 * How tightly a view packs its cells.
 *
 * Geometry, not colour: the contract publishes the live density tokens at their
 * comfortable values plus explicit compact counterparts, and the react-core sheet
 * re-scopes the live ones under `[data-density="compact"]`. So this is one attribute
 * stamped on a subtree root, and every rule reading a live token follows by
 * custom-property inheritance — including the control heights `Button`, `Input` and
 * `Select` already read, which is why a compact DataView also gets compact controls
 * without either component knowing about the other.
 */
export type DataViewDensity = "comfortable" | "compact";

/**
 * A column's declared track: a step, not a length.
 *
 * The three steps are the three bands the framework's own tables actually declare, and there are
 * deliberately no others. `lg` and a content-hugging step were both drafted and dropped for the
 * same reason a component with no consumer is dropped — nothing asks for them, and a step is
 * additive to add and breaking to remove. The scale is rem, so a declared track follows the root
 * font size instead of pinning a column to one display's pixels.
 */
export type ColumnWidth = "xs" | "sm" | "md";

/** Typed column meta the DataView-specific features read. */
export interface DataViewColumnMeta {
  /** Human-readable name used in the column-settings menu (falls back to the header). */
  label?: UiText;
  /** Slot in the auto-composed card layout. */
  mobileSlot?: DataViewMobileSlot;
  /**
   * The column's declared minimum track. Omit for content-based auto sizing.
   *
   * A **minimum**, because that is the only thing `table-layout: auto` cannot take away: a
   * specified `width` is a preference the algorithm shrinks to fit, which is why the px hint this
   * replaced did nothing at all. A user's own resize replaces the declared track entirely rather
   * than fighting it.
   */
  width?: ColumnWidth;
}

/**
 * A numeric column drawn as an inline bar (ADR 0169 §5): the cell's number beside a `Meter`,
 * so the column reads as magnitudes at a glance and every value is still printed.
 */
export interface DataViewBar {
  /** The top of every bar's range (default: the largest value among the rows shown). */
  max?: number;
  /** How the value prints, as `Intl.NumberFormatOptions` (default: a plain number). */
  format?: Intl.NumberFormatOptions;
}

/** Generic, typed column definition for {@link DataView}. */
export interface DataViewColumn<T> {
  /** Stable id — used for sorting/filter ids, visibility, ordering and sizing. */
  id: string;
  /** Header content. */
  header: UiText;
  /** The raw value of this column for a row (used by default cell rendering). */
  accessor?: (row: T) => unknown;
  /**
   * Custom cell renderer. Without one the accessor's value is rendered by the shared default:
   * `null` / `undefined` render nothing, a `Date` renders through the app's locale (the same
   * `useFormatDate` the framework's own screens use), and anything else is `String(value)`.
   * Table and card layouts share that default, so a column reads the same on both.
   */
  cell?: (row: T) => ReactNode;
  /** Whether the header offers the 3-state sort toggle (default true). */
  enableSorting?: boolean;
  /**
   * A status dot before the cell's text, in the tone the row's state calls for (ADR 0169 §5):
   * the quiet form of a status column, for a column where most rows are fine and a pill on
   * every one of them is noise. The text is the word the tone stands for, so a cell with no
   * text gets no dot; `null` or `undefined` leaves the row's cell plain.
   */
  status?: (row: T) => BadgeTone | null | undefined;
  /**
   * Draw the column's number as an inline bar (ADR 0169 §5), scaled to the largest value on
   * the rows shown unless `max` is given — so a page of results compares at a glance and a
   * page you move to rescales. The accessor's number is what is drawn and printed; a `cell`
   * renderer is not used for a bar, and a row whose value is not a number renders as text.
   */
  bar?: true | DataViewBar;
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

/**
 * Every user-facing string the DataView renders, overridable per instance through its
 * `strings` prop.
 *
 * The defaults are not here. Each key is read from the active locale's `TerpStrings`, under
 * the same name with a `dataView` prefix (`searchPlaceholder` is `dataViewSearchPlaceholder`),
 * so a DataView speaks whatever language the app's `LocaleProvider` does and a catalog that
 * leaves one of them out is refused. A per-instance override wins over the locale.
 */
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
  resultsRange: UiText; // "{from}–{to} of {total} …": yours, used as given — the locale's has plural forms
  pageOf: UiText; // "Page {page} of {pages}"
  firstPage: UiText;
  previousPage: UiText;
  nextPage: UiText;
  lastPage: UiText;
  selectAllPage: UiText;
  selectRow: UiText;
  selected: UiText; // "{count} selected"
  selectAllResults: UiText; // "… {total} …": yours, used as given — the locale's has plural forms
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

/** Resolve a row-action boolean-or-predicate flag against a row. */
export function resolveRowFlag<T>(
  flag: boolean | ((row: T) => boolean) | undefined,
  row: T,
): boolean {
  return typeof flag === "function" ? flag(row) : flag === true;
}
