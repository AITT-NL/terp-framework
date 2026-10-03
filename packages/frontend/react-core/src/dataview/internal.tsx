import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";

import { useFormatDate } from "../format";
import { Meter } from "../Meter";
import { injectTerpStyles } from "../styles";
import { Menu, MenuItem } from "../ui/Menu";
import { fillPlaceholders, isPluralText, usePlural, useStrings, useUiText } from "../uiText";
import type { PluralText, ResolveUiText, TerpStrings, UiText } from "../uiText";

import type { DataViewColumn, DataViewStrings } from "./types";

injectTerpStyles();

/**
 * The strings a DataView part reads: the locale's, under an instance's overrides.
 *
 * Wider than {@link DataViewStrings} in two keys. From the locale, the result range and the
 * select-all label are {@link PluralText}, one form per plural category; an instance that
 * overrides them passes one `UiText`, which is its own wording and is used as given.
 */
export type DataViewTextSet = Omit<DataViewStrings, "resultsRange" | "selectAllResults"> & {
  resultsRange: CountedText;
  selectAllResults: CountedText;
};

/** A count-bearing string: the locale's plural forms, or an instance's own wording. */
type CountedText = UiText | PluralText;

/** Internal: merged strings + resolver every DataView sub-component reads. */
export interface DataViewTextApi {
  strings: DataViewTextSet;
  resolve: ResolveUiText;
  /** Resolve a string with `{placeholder}`s and fill them. */
  format: (text: UiText, values: Record<string, string | number>) => string;
  /** The same for a string whose wording depends on *count*: choose its form, then fill it. */
  formatCount: (
    text: CountedText,
    count: number,
    values: Record<string, string | number>,
  ) => string;
}

/**
 * The DataView's strings, read out of the framework table.
 *
 * They used to be a second table of English defaults that only the per-instance `strings` prop
 * could change. A locale catalog is typed against `TerpStrings`, so it had nowhere to put a
 * DataView translation, and the completeness check that refuses a half-translated shell walked
 * a table these strings were not in: under a Dutch locale every DataView rendered its toolbar
 * and footer in English, the framework's own admin screens included, with every gate green.
 *
 * Written out rather than derived from the key names, so a missing or misspelt key is a type
 * error here and not an `undefined` on screen.
 */
function dataViewStrings(strings: TerpStrings): DataViewTextSet {
  return {
    searchPlaceholder: strings.dataViewSearchPlaceholder,
    clearSearch: strings.dataViewClearSearch,
    clearFilters: strings.dataViewClearFilters,
    viewOptions: strings.dataViewViewOptions,
    columns: strings.dataViewColumns,
    moveUp: strings.dataViewMoveUp,
    moveDown: strings.dataViewMoveDown,
    tableView: strings.dataViewTableView,
    cardView: strings.dataViewCardView,
    pageSize: strings.dataViewPageSize,
    resultsRange: strings.dataViewResultsRange,
    pageOf: strings.dataViewPageOf,
    firstPage: strings.dataViewFirstPage,
    previousPage: strings.dataViewPreviousPage,
    nextPage: strings.dataViewNextPage,
    lastPage: strings.dataViewLastPage,
    selectAllPage: strings.dataViewSelectAllPage,
    selectRow: strings.dataViewSelectRow,
    selected: strings.dataViewSelected,
    selectAllResults: strings.dataViewSelectAllResults,
    clearSelection: strings.dataViewClearSelection,
    moreActions: strings.dataViewMoreActions,
    actions: strings.dataViewActions,
    openRow: strings.dataViewOpenRow,
    expandRow: strings.dataViewExpandRow,
    collapseRow: strings.dataViewCollapseRow,
    empty: strings.dataViewEmpty,
    loading: strings.dataViewLoading,
    refreshing: strings.dataViewRefreshing,
    errorTitle: strings.dataViewErrorTitle,
    resizeColumn: strings.dataViewResizeColumn,
  };
}

/**
 * A DataView's per-instance overrides, and nothing else.
 *
 * The context carries only what the instance said, never a finished set of strings, so there is
 * no default value to go stale: a sub-component rendered on its own — a `DataViewPagination`
 * outside any `DataView` — reads the active locale exactly as one inside does. The context's
 * default used to BE a finished set, English strings and a resolver that ignored the locale, so
 * a fix to the provider alone would have left every standalone part exactly as it was.
 */
const DataViewOverridesContext = createContext<Partial<DataViewStrings> | undefined>(undefined);

export function useDataViewText(): DataViewTextApi {
  const overrides = useContext(DataViewOverridesContext);
  const framework = useStrings();
  const resolve = useUiText();
  const plural = usePlural();
  return useMemo<DataViewTextApi>(
    () => ({
      strings: { ...dataViewStrings(framework), ...overrides },
      resolve,
      format: (text, values) => fillPlaceholders(resolve(text), values),
      formatCount: (text, count, values) =>
        fillPlaceholders(isPluralText(text) ? plural(text, count) : resolve(text), values),
    }),
    [framework, overrides, resolve, plural],
  );
}

/**
 * Stringify a cell for a column that declares no `cell` renderer.
 *
 * One hook rather than a helper per renderer, because there WERE two: the table had a private
 * `formatCell` and the mobile card list inlined the same three lines. They agreed, so nothing
 * caught that they were two, and the first change to either would have made a row render one way
 * on a desktop and another on a phone.
 *
 * The `Date` branch is why that mattered. `accessor` returns `unknown`, so a `Date` is type-legal
 * and `String(value)` renders `Wed Aug 21 2026 00:00:00 GMT+0200 (Central European Summer Time)`
 * in a table cell. Nothing in this tree returns one today, which is exactly why it was worth
 * closing now rather than after an app discovered it.
 */
export function useCellFormatter(): (value: unknown) => ReactNode {
  const formatDate = useFormatDate();
  return useCallback(
    (value: unknown) => {
      if (value === null || value === undefined) {
        return null;
      }
      if (value instanceof Date) {
        return formatDate(value);
      }
      return String(value);
    },
    [formatDate],
  );
}

/** A bar's value prints as a plain number unless the column says otherwise. */
const PLAIN_NUMBER: Intl.NumberFormatOptions = {};

/**
 * The top of each bar column's range for the rows shown: the column's own `max`, or the largest
 * number among the rows. Computed once per render of the rows rather than per cell.
 */
export function barMaxima<T>(
  columns: readonly DataViewColumn<T>[],
  rows: readonly T[],
): ReadonlyMap<string, number> {
  const maxima = new Map<string, number>();
  for (const column of columns) {
    if (column.bar === undefined) {
      continue;
    }
    const declared = column.bar === true ? undefined : column.bar.max;
    if (declared !== undefined) {
      maxima.set(column.id, declared);
      continue;
    }
    let top = 0;
    for (const row of rows) {
      const value = column.accessor?.(row);
      if (typeof value === "number" && Number.isFinite(value) && value > top) {
        top = value;
      }
    }
    maxima.set(column.id, top);
  }
  return maxima;
}

/**
 * A cell's content, the same in the table and in the cards: the column's own renderer or the
 * shared default, and then its presentation — a bar drawn as a `Meter`, or a status dot before
 * the text.
 *
 * One function for both layouts for the reason {@link useCellFormatter} gives: two copies agree
 * until the first change to either, and then a row renders one way on a desk and another on a
 * phone.
 */
export function useCellRenderer(): <T>(
  column: DataViewColumn<T>,
  row: T,
  maxima: ReadonlyMap<string, number>,
) => ReactNode {
  const formatCell = useCellFormatter();
  return useCallback(
    <T,>(column: DataViewColumn<T>, row: T, maxima: ReadonlyMap<string, number>) => {
      if (column.bar !== undefined) {
        const value = column.accessor?.(row);
        if (typeof value === "number" && Number.isFinite(value)) {
          return (
            <Meter
              label={column.header}
              value={value}
              max={maxima.get(column.id) ?? value}
              format={(column.bar === true ? undefined : column.bar.format) ?? PLAIN_NUMBER}
            />
          );
        }
      }
      const content =
        column.cell !== undefined ? column.cell(row) : formatCell(column.accessor?.(row));
      const tone = column.status?.(row);
      // The dot stands for a word, so it is drawn only beside one.
      if (
        tone === undefined ||
        tone === null ||
        content === null ||
        content === undefined ||
        content === false ||
        content === ""
      ) {
        return content;
      }
      return (
        <span data-terp="dataview-status">
          <span data-terp="dataview-status-dot" data-tone={tone} aria-hidden="true" />
          {content}
        </span>
      );
    },
    [formatCell],
  );
}

export function DataViewTextProvider({
  overrides,
  children,
}: {
  overrides?: Partial<DataViewStrings>;
  children: ReactNode;
}) {
  return (
    <DataViewOverridesContext.Provider value={overrides}>{children}</DataViewOverridesContext.Provider>
  );
}

/**
 * Internal DataView wrapper over the shared react-core Menu primitive.
 */
export function DataViewMenu({
  trigger,
  triggerLabel,
  align = "end",
  defaultOpen,
  children,
}: {
  /** Trigger content (an icon or a label). */
  trigger: ReactNode;
  /** Accessible name of the trigger button. */
  triggerLabel: string;
  align?: "start" | "end";
  /** Open on mount — threaded to `Menu`, which has carried this since the overlays moved. */
  defaultOpen?: boolean;
  /** Panel content; render-prop so items can close the menu after acting. */
  children: (close: () => void) => ReactNode;
}) {
  return (
    <Menu trigger={trigger} triggerLabel={triggerLabel} align={align} defaultOpen={defaultOpen}>
      {({ close }) => children(() => close(false))}
    </Menu>
  );
}

/** Internal: one item inside a {@link DataViewMenu}. */
export function DataViewMenuItem({
  label,
  destructive = false,
  disabled = false,
  selected,
  icon,
  onSelect,
}: {
  label: string;
  destructive?: boolean;
  disabled?: boolean;
  /** Marks one choice in a mutually exclusive menu (renders `menuitemradio`). */
  selected?: boolean;
  icon?: ReactNode;
  onSelect: () => void;
}) {
  return (
    <MenuItem
      label={label}
      icon={icon}
      selected={selected}
      destructive={destructive}
      disabled={disabled}
      onSelect={onSelect}
    />
  );
}
