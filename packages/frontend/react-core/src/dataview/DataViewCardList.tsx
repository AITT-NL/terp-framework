import type { ReactNode } from "react";

import type { BadgeTone } from "../ui/Badge";
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
  getRowTone?: (row: T) => BadgeTone | null;
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
    <ul data-terp="dataview-card-list">
      {props.rows.map((row) => {
        const rowId = props.getRowId(row);
        const expanded = props.isExpanded(rowId);
        const clickable = props.onRowClick !== undefined;
        const tone = props.getRowTone?.(row) ?? null;
        return (
          <li key={rowId}>
            <div
              onClick={clickable ? () => props.onRowClick?.(row) : undefined}
              data-terp="dataview-card"
              data-clickable={clickable || undefined}
              data-tone={tone ?? undefined}
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
                />
              )}
              <div data-terp="dataview-card-main">
                {props.renderExpanded !== undefined && (
                  <DataViewExpandToggle
                    expanded={expanded}
                    onToggle={() => props.onToggleExpanded(rowId)}
                  />
                )}
                {props.selectionEnabled && (
                  <span onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={resolve(strings.selectRow)}
                      checked={props.isSelected(rowId)}
                      onChange={() => props.onToggleSelected(rowId)}
                    />
                  </span>
                )}
                <div data-terp="dataview-card-body">
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
                <div data-terp="dataview-card-expanded">
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
    <div data-terp="dataview-card-fields">
      <div data-terp="dataview-card-heading">
        <span data-terp="dataview-card-title">{title}</span>
        {status !== null && (
          <span data-terp="dataview-card-status">{status}</span>
        )}
      </div>
      {subtitle !== null && <span data-terp="dataview-card-meta">{subtitle}</span>}
      {date !== null && <span data-terp="dataview-card-meta">{date}</span>}
    </div>
  );
}
