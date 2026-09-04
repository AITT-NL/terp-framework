import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import type { BadgeTone } from "../ui/Badge";
import type { UiText } from "../uiText";
import { DataViewExpandToggle, DataViewExpandableRow } from "./DataViewExpandableRow";
import { DataViewRowActions } from "./DataViewRowActions";
import type { DataViewRowActionsLayout } from "./DataViewRowActions";
import { SortAscGlyph, SortDescGlyph, SortNoneGlyph } from "./glyphs";
import { useCellFormatter, useDataViewText } from "./internal";

injectTerpStyles();
import type {
  ColumnWidth,
  DataViewColumn,
  DataViewRowAction,
} from "./types";

const MIN_COLUMN_WIDTH = 60;

export interface DataViewTableProps<T> {
  rows: T[];
  columns: DataViewColumn<T>[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  getRowLabel?: (row: T) => UiText;
  getRowTone?: (row: T) => BadgeTone | null;
  isMobile: boolean;
  // Sorting
  sorting: { id: string; desc: boolean }[];
  onToggleSort: (columnId: string) => void;
  // Sizing
  columnSizing: Record<string, number>;
  onCommitColumnSizing: (sizing: Record<string, number>) => void;
  // Selection
  selectionEnabled: boolean;
  isSelected: (rowId: string) => boolean;
  onToggleSelected: (rowId: string) => void;
  allPageSelected: boolean;
  somePageSelected: boolean;
  onToggleSelectPage: () => void;
  // Expansion
  renderExpanded?: (row: T) => ReactNode;
  isRowExpandable?: (row: T) => boolean;
  isExpanded: (rowId: string) => boolean;
  onToggleExpanded: (rowId: string) => void;
  // Actions
  rowActions?: (row: T) => DataViewRowAction<T>[];
  rowActionsLayout: DataViewRowActionsLayout;
}

/**
 * The table layout of {@link DataView}: sortable, resizable headers; system columns
 * (expand → select → user columns → actions); row click, selection, expansion.
 *
 * Width resolution precedence: pinned system columns → user-resized → static meta
 * hint → auto (content-based).
 */
export function DataViewTable<T>(props: DataViewTableProps<T>) {
  const { strings, resolve, format } = useDataViewText();
  const formatCell = useCellFormatter();
  const tableRef = useRef<HTMLTableElement>(null);

  // Live widths during a resize drag only — persisted once, on pointer-up.
  const [liveSizing, setLiveSizing] = useState<Record<string, number> | null>(null);
  const dragCleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => () => dragCleanupRef.current?.(), []);

  const startResize = useCallback(
    (columnId: string, startX: number) => {
      const table = tableRef.current;
      if (table === null) {
        return;
      }
      // Snapshot every rendered width so switching from auto to fixed layout does
      // not make the other columns jump.
      const snapshot: Record<string, number> = {};
      for (const th of table.querySelectorAll<HTMLTableCellElement>("th[data-column-id]")) {
        const id = th.dataset.columnId;
        if (id !== undefined) {
          snapshot[id] = th.offsetWidth;
        }
      }
      const startWidth = snapshot[columnId] ?? MIN_COLUMN_WIDTH;
      let current = snapshot;
      setLiveSizing(snapshot);

      const onPointerMove = (event: PointerEvent) => {
        const width = Math.max(MIN_COLUMN_WIDTH, startWidth + (event.clientX - startX));
        current = { ...current, [columnId]: width };
        setLiveSizing(current);
      };
      const cleanup = () => {
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        dragCleanupRef.current = null;
      };
      const onPointerUp = () => {
        cleanup();
        setLiveSizing(null);
        // ONLY the dragged column is committed, though `current` holds a width for every one of
        // them. The snapshot exists to stop the other columns jumping when the layout flips to
        // fixed for the duration of the drag; persisting it would tell the view state the user had
        // sized the whole table, and `stepOf` would then suppress every declared track — one drag
        // anywhere would switch the floors off table-wide, and durably so for an app with a view
        // state repository. `commitColumnSizing` merges, so earlier resizes survive this.
        props.onCommitColumnSizing({ [columnId]: current[columnId] ?? startWidth }); // one write per drag
      };
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
      dragCleanupRef.current = cleanup;
    },
    [props.onCommitColumnSizing],
  );

  /**
   * The user's own width for a column, in px, or `undefined` if they have not resized it.
   *
   * This and {@link stepOf} are deliberately exclusive: a resized column emits an inline `width`
   * and NO `data-width`, so the declared step stops applying the moment the user disagrees with
   * it. Emitting both would put a `min-inline-size` from the sheet against an inline `width`, and
   * the minimum wins — dragging a column below its declared step would spring back and the
   * resizer would look broken.
   */
  const resizedWidthOf = (column: DataViewColumn<T>): number | undefined =>
    liveSizing?.[column.id] ?? props.columnSizing[column.id];

  /** The declared track, which applies only while the column is at its default width. */
  const stepOf = (column: DataViewColumn<T>): ColumnWidth | undefined =>
    resizedWidthOf(column) === undefined ? column.meta?.width : undefined;

  // Whether the view has an expand COLUMN at all: one row with something behind it is
  // enough, because the column has to be there for the rows that do. Which rows get a
  // toggle inside it is a separate question, asked per row below -- collapsing the two
  // is what put a chevron on every row of a view where only some had anything.
  const expandableRows = props.renderExpanded === undefined
    ? []
    : props.rows.filter((row) => props.isRowExpandable?.(row) ?? true);
  const hasExpand = expandableRows.length > 0;
  const hasActions = props.rowActions !== undefined;
  const columnCount =
    props.columns.length + (hasExpand ? 1 : 0) + (props.selectionEnabled ? 1 : 0) + (hasActions ? 1 : 0);

  const selectAllRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectAllRef.current !== null) {
      selectAllRef.current.indeterminate = props.somePageSelected && !props.allPageSelected;
    }
  }, [props.somePageSelected, props.allPageSelected]);

  return (
    <table
      ref={tableRef}
      data-terp="dataview-table"
      data-resizing={liveSizing !== null || undefined}
    >
      <thead>
        <tr>
          {hasExpand && <th data-terp="dataview-expand-cell" aria-hidden />}
          {props.selectionEnabled && (
            <th data-terp="dataview-select-cell">
              <input
                ref={selectAllRef}
                type="checkbox"
                aria-label={resolve(strings.selectAllPage)}
                checked={props.allPageSelected}
                onChange={props.onToggleSelectPage}
              />
            </th>
          )}
          {props.columns.map((column) => {
            const sort = props.sorting.find((entry) => entry.id === column.id);
            const sortable = column.enableSorting !== false;
            const width = resizedWidthOf(column);
            const step = stepOf(column);
            return (
              <th
                key={column.id}
                data-column-id={column.id}
                data-width={step}
                aria-sort={
                  sort === undefined ? undefined : sort.desc ? "descending" : "ascending"
                }
                style={width === undefined ? undefined : { width }}
              >
                {sortable ? (
                  <button
                    type="button"
                    data-terp="dataview-column-sort"
                    onClick={() => props.onToggleSort(column.id)}
                  >
                    {resolve(column.header)}
                    {sort === undefined ? (
                      <SortNoneGlyph size={12} />
                    ) : sort.desc ? (
                      <SortDescGlyph size={12} />
                    ) : (
                      <SortAscGlyph size={12} />
                    )}
                  </button>
                ) : (
                  resolve(column.header)
                )}
                <span
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={`${resolve(strings.resizeColumn)}: ${resolve(column.meta?.label ?? column.header)}`}
                  data-terp="dataview-column-resizer"
                  onPointerDown={(event) => {
                    event.preventDefault();
                    startResize(column.id, event.clientX);
                  }}
                />
              </th>
            );
          })}
          {hasActions && (
            <th data-terp="dataview-actions-cell">
              <span>{resolve(strings.actions)}</span>
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {props.rows.map((row) => {
          const rowId = props.getRowId(row);
          const expandable = props.isRowExpandable?.(row) ?? true;
          const expanded = expandable && props.isExpanded(rowId);
          const clickable = props.onRowClick !== undefined;
          const tone = props.getRowTone?.(row) ?? null;
          return (
            <RowGroup key={rowId}>
              <tr
                onClick={clickable ? () => props.onRowClick?.(row) : undefined}
                data-terp="dataview-row"
                data-clickable={clickable || undefined}
                data-selected={props.isSelected(rowId) || undefined}
                data-tone={tone ?? undefined}
              >
                {hasExpand && (
                  <td data-terp="dataview-expand-cell">
                    {/* The cell is always rendered when the view has the column, so the
                        remaining cells stay aligned; only the control is conditional. */}
                    {expandable && (
                      <DataViewExpandToggle
                        expanded={expanded}
                        onToggle={() => props.onToggleExpanded(rowId)}
                      />
                    )}
                  </td>
                )}
                {props.selectionEnabled && (
                  <td data-terp="dataview-select-cell" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={resolve(strings.selectRow)}
                      checked={props.isSelected(rowId)}
                      onChange={() => props.onToggleSelected(rowId)}
                    />
                  </td>
                )}
                {props.columns.map((column) => (
                  <td key={column.id}>
                    {clickable && column === props.columns[0] && (
                      <button
                        type="button"
                        data-terp="dataview-row-open"
                        aria-label={format(strings.openRow, {
                          label: resolve(props.getRowLabel?.(row) ?? ""),
                        })}
                        onClick={(event) => {
                          event.stopPropagation();
                          props.onRowClick?.(row);
                        }}
                      />
                    )}
                    {column.cell !== undefined
                      ? column.cell(row)
                      : formatCell(column.accessor?.(row))}
                  </td>
                ))}
                {hasActions && (
                  <td data-terp="dataview-actions-cell">
                    <DataViewRowActions
                      row={row}
                      actions={props.rowActions?.(row) ?? []}
                      layout={props.rowActionsLayout}
                      isMobile={props.isMobile}
                    />
                  </td>
                )}
              </tr>
              {expanded && props.renderExpanded !== undefined && (
                <DataViewExpandableRow colSpan={columnCount}>
                  {props.renderExpanded(row)}
                </DataViewExpandableRow>
              )}
            </RowGroup>
          );
        })}
      </tbody>
    </table>
  );
}

/** Keys a row + its expansion panel together without extra DOM. */
function RowGroup({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

