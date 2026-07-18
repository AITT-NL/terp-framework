import type { CSSProperties, ReactNode } from "react";

import type { UiText } from "../uiText";

import { DataViewExpandToggle } from "./DataViewExpandableRow";
import { DataViewRowActions } from "./DataViewRowActions";
import { useDataViewText } from "./internal";
import type { DataViewColumn, DataViewRowAction } from "./types";

export interface DataViewCardListProps<T> {
  rows: T[];
  columns: DataViewColumn<T>[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  getRowLabel?: (row: T) => UiText;
  /** Escape hatch for fully custom cards. */
  renderCard?: (row: T) => ReactNode;
  // Selection
  selectionEnabled: boolean;
  isSelected: (rowId: string) => boolean;
  onToggleSelected: (rowId: string) => void;
  // Expansion
  renderExpanded?: (row: T) => ReactNode;
  isExpanded: (rowId: string) => boolean;
  onToggleExpanded: (rowId: string) => void;
  // Actions
  rowActions?: (row: T) => DataViewRowAction<T>[];
}

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

function slotValue<T>(
  columns: DataViewColumn<T>[],
  row: T,
  slot: "title" | "subtitle" | "status" | "date",
): ReactNode {
  const column = columns.find((candidate) => candidate.meta?.mobileSlot === slot);
  if (column === undefined) {
    return null;
  }
  if (column.cell !== undefined) {
    return column.cell(row);
  }
  const value = column.accessor?.(row);
  return value === null || value === undefined ? null : String(value);
}

/**
 * The stacked card layout: each row becomes a card auto-composed from the columns'
 * `mobileSlot` meta (title, subtitle, status, date), with `renderCard` as a full
 * escape hatch. Selection, row actions and expansion keep working in card view
 * (standard actions collapse into the ellipsis menu).
 */
export function DataViewCardList<T>(props: DataViewCardListProps<T>) {
  const { strings, resolve, format } = useDataViewText();

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: "var(--space-2)", display: "grid", gap: "var(--space-2)" }}>
      {props.rows.map((row) => {
        const rowId = props.getRowId(row);
        const expanded = props.isExpanded(rowId);
        const clickable = props.onRowClick !== undefined;
        return (
          <li key={rowId}>
            <div
              onClick={clickable ? () => props.onRowClick?.(row) : undefined}
              data-terp={clickable ? "dataview-card" : undefined}
              style={{
                display: "grid",
                gap: "var(--space-2)",
                padding: "var(--space-3)",
                background: "var(--color-neutral-0)",
                border: "1px solid var(--color-neutral-200)",
                borderRadius: "var(--radius-lg)",
                boxShadow: "var(--shadow-sm)",
                cursor: clickable ? "pointer" : undefined,
              }}
            >
              {clickable && (
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
              <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--space-2)" }}>
                {props.renderExpanded !== undefined && (
                  <DataViewExpandToggle
                    expanded={expanded}
                    onToggle={() => props.onToggleExpanded(rowId)}
                  />
                )}
                {props.selectionEnabled && (
                  <span onClick={(event) => event.stopPropagation()} style={{ display: "inline-flex" }}>
                    <input
                      type="checkbox"
                      aria-label={resolve(strings.selectRow)}
                      checked={props.isSelected(rowId)}
                      onChange={() => props.onToggleSelected(rowId)}
                    />
                  </span>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  {props.renderCard !== undefined ? (
                    props.renderCard(row)
                  ) : (
                    <DefaultCardBody row={row} columns={props.columns} />
                  )}
                </div>
                {props.rowActions !== undefined && (
                  <DataViewRowActions
                    row={row}
                    actions={props.rowActions(row)}
                    layout="menu"
                    isMobile
                  />
                )}
              </div>
              {expanded && props.renderExpanded !== undefined && (
                <div
                  style={{
                    borderTop: "1px solid var(--color-neutral-200)",
                    paddingTop: "var(--space-2)",
                  }}
                >
                  {props.renderExpanded(row)}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function DefaultCardBody<T>({ row, columns }: { row: T; columns: DataViewColumn<T>[] }) {
  const title = slotValue(columns, row, "title");
  const subtitle = slotValue(columns, row, "subtitle");
  const status = slotValue(columns, row, "status");
  const date = slotValue(columns, row, "date");
  return (
    <div style={{ display: "grid", gap: "var(--space-1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
        <span style={{ fontWeight: "var(--font-weight-medium)" as never }}>{title}</span>
        {status !== null && (
          <span
            style={{
              fontSize: "var(--font-size-sm)",
              padding: "0 var(--space-2)",
              background: "var(--color-neutral-100)",
              borderRadius: "var(--radius-full)",
              color: "var(--color-neutral-700)",
            }}
          >
            {status}
          </span>
        )}
      </div>
      {subtitle !== null && (
        <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-neutral-500)" }}>
          {subtitle}
        </span>
      )}
      {date !== null && (
        <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-neutral-500)" }}>
          {date}
        </span>
      )}
    </div>
  );
}
