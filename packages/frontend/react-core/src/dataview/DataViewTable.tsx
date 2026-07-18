import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import type { UiText } from "../uiText";
import { DataViewExpandToggle, DataViewExpandableRow } from "./DataViewExpandableRow";
import { DataViewRowActions } from "./DataViewRowActions";
import type { DataViewRowActionsLayout } from "./DataViewRowActions";
import { SortAscGlyph, SortDescGlyph, SortNoneGlyph } from "./glyphs";
import { useDataViewText } from "./internal";

injectTerpStyles();
import type { DataViewColumn, DataViewRowAction } from "./types";

const MIN_COLUMN_WIDTH = 60;

export interface DataViewTableProps<T> {
  rows: T[];
  columns: DataViewColumn<T>[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  getRowLabel?: (row: T) => UiText;
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
  isExpanded: (rowId: string) => boolean;
  onToggleExpanded: (rowId: string) => void;
  // Actions
  rowActions?: (row: T) => DataViewRowAction<T>[];
  rowActionsLayout: DataViewRowActionsLayout;
}

const headerCellStyle: CSSProperties = {
  position: "relative",
  padding: "var(--space-2) var(--space-3)",
  textAlign: "left",
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-semibold)" as never,
  color: "var(--color-neutral-500)",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  borderBottom: "1px solid var(--color-neutral-200)",
  whiteSpace: "nowrap",
  background: "var(--color-neutral-0)",
};

const bodyCellStyle: CSSProperties = {
  padding: "var(--space-3)",
  borderBottom: "1px solid var(--color-neutral-100)",
  fontSize: "var(--font-size-sm)",
  color: "var(--color-neutral-900)",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const recordButtonStyle: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * The table layout of {@link DataView}: sortable, resizable headers; system columns
 * (expand → select → user columns → actions); row click, selection, expansion.
 *
 * Width resolution precedence: pinned system columns → user-resized → static meta
 * hint → auto (content-based).
 */
export function DataViewTable<T>(props: DataViewTableProps<T>) {
  const { strings, resolve, format } = useDataViewText();
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
        props.onCommitColumnSizing(current); // one persistence write per drag
      };
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
      dragCleanupRef.current = cleanup;
    },
    [props.onCommitColumnSizing],
  );

  const widthOf = (column: DataViewColumn<T>): number | string | undefined => {
    const live = liveSizing?.[column.id];
    if (live !== undefined) {
      return live;
    }
    const resized = props.columnSizing[column.id];
    if (resized !== undefined) {
      return resized;
    }
    return column.meta?.width;
  };

  const hasExpand = props.renderExpanded !== undefined;
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
      style={{
        width: "100%",
        borderCollapse: "collapse",
        tableLayout: liveSizing !== null ? "fixed" : "auto",
      }}
    >
      <thead>
        <tr>
          {hasExpand && <th style={{ ...headerCellStyle, width: 40 }} aria-hidden />}
          {props.selectionEnabled && (
            <th style={{ ...headerCellStyle, width: 40 }}>
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
            const width = widthOf(column);
            return (
              <th
                key={column.id}
                data-column-id={column.id}
                aria-sort={
                  sort === undefined ? undefined : sort.desc ? "descending" : "ascending"
                }
                style={{ ...headerCellStyle, width }}
              >
                {sortable ? (
                  <button
                    type="button"
                    onClick={() => props.onToggleSort(column.id)}
                    style={{
                      font: "inherit",
                      color: "inherit",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "var(--space-1)",
                      background: "transparent",
                      border: "none",
                      padding: 0,
                      cursor: "pointer",
                    }}
                  >
                    {resolve(column.header)}
                    {sort === undefined ? (
                      <SortNoneGlyph size={12} style={{ opacity: 0.5 }} />
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
                  onPointerDown={(event) => {
                    event.preventDefault();
                    startResize(column.id, event.clientX);
                  }}
                  style={{
                    position: "absolute",
                    top: 0,
                    right: -3,
                    width: 7,
                    height: "100%",
                    cursor: "col-resize",
                    zIndex: 1,
                    touchAction: "none",
                  }}
                />
              </th>
            );
          })}
          {hasActions && (
            <th style={{ ...headerCellStyle, width: 56 }}>
              <span
                style={{
                  position: "absolute",
                  width: 1,
                  height: 1,
                  padding: 0,
                  margin: -1,
                  overflow: "hidden",
                  clip: "rect(0 0 0 0)",
                  whiteSpace: "nowrap",
                  border: 0,
                }}
              >
                {resolve(strings.actions)}
              </span>
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {props.rows.map((row) => {
          const rowId = props.getRowId(row);
          const expanded = props.isExpanded(rowId);
          const clickable = props.onRowClick !== undefined;
          return (
            <RowGroup key={rowId}>
              <tr
                onClick={clickable ? () => props.onRowClick?.(row) : undefined}
                data-terp={clickable ? "dataview-row" : undefined}
                data-selected={props.isSelected(rowId) || undefined}
                style={{
                  cursor: clickable ? "pointer" : undefined,
                  background: props.isSelected(rowId) ? "var(--color-neutral-50)" : undefined,
                }}
              >
                {hasExpand && (
                  <td style={bodyCellStyle}>
                    <DataViewExpandToggle
                      expanded={expanded}
                      onToggle={() => props.onToggleExpanded(rowId)}
                    />
                  </td>
                )}
                {props.selectionEnabled && (
                  <td style={bodyCellStyle} onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={resolve(strings.selectRow)}
                      checked={props.isSelected(rowId)}
                      onChange={() => props.onToggleSelected(rowId)}
                    />
                  </td>
                )}
                {props.columns.map((column) => (
                  <td key={column.id} style={bodyCellStyle}>
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
                        style={recordButtonStyle}
                      />
                    )}
                    {column.cell !== undefined
                      ? column.cell(row)
                      : formatCell(column.accessor?.(row))}
                  </td>
                ))}
                {hasActions && (
                  <td style={{ ...bodyCellStyle, textAlign: "right" }}>
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

function formatCell(value: unknown): ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  return String(value);
}
