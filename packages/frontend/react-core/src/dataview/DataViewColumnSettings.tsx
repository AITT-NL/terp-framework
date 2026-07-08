import { ArrowDownGlyph, ArrowUpGlyph, ColumnsGlyph } from "./glyphs";
import { DataViewMenu, useDataViewText } from "./internal";
import type { DataViewColumn } from "./types";

export interface DataViewColumnSettingsProps<T> {
  /** The user columns in effective order (system columns are never listed here). */
  columns: DataViewColumn<T>[];
  columnVisibility: Record<string, boolean>;
  onColumnVisibleChange: (columnId: string, visible: boolean) => void;
  onMoveColumn: (columnId: string, direction: -1 | 1) => void;
}

/**
 * The "view options" menu: per-column show/hide checkboxes and up/down reordering.
 * Only user columns appear — the pinned system columns (select/expand/actions) are
 * never hideable or reorderable, and are skipped when computing reorder targets
 * because this list simply does not contain them.
 */
export function DataViewColumnSettings<T>({
  columns,
  columnVisibility,
  onColumnVisibleChange,
  onMoveColumn,
}: DataViewColumnSettingsProps<T>) {
  const { strings, resolve } = useDataViewText();

  return (
    <DataViewMenu
      trigger={
        <>
          <ColumnsGlyph />
          <span style={{ fontSize: "var(--font-size-sm)" }}>{resolve(strings.viewOptions)}</span>
        </>
      }
      triggerLabel={resolve(strings.viewOptions)}
    >
      {() => (
        <div style={{ display: "grid", gap: "var(--space-1)" }}>
          <div
            style={{
              padding: "var(--space-1) var(--space-2)",
              fontSize: "var(--font-size-sm)",
              fontWeight: "var(--font-weight-medium)" as never,
              color: "var(--color-neutral-500)",
            }}
          >
            {resolve(strings.columns)}
          </div>
          {columns.map((column, index) => {
            const label = resolve(column.meta?.label ?? column.header);
            const visible = columnVisibility[column.id] !== false;
            return (
              <div
                key={column.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  padding: "var(--space-1) var(--space-2)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    flex: 1,
                    cursor: "pointer",
                    fontSize: "var(--font-size-sm)",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={visible}
                    onChange={(event) => onColumnVisibleChange(column.id, event.target.checked)}
                    aria-label={label}
                  />
                  {label}
                </label>
                <button
                  type="button"
                  aria-label={`${resolve(strings.moveUp)}: ${label}`}
                  disabled={index === 0}
                  onClick={() => onMoveColumn(column.id, -1)}
                  style={reorderButtonStyle(index === 0)}
                >
                  <ArrowUpGlyph size={14} />
                </button>
                <button
                  type="button"
                  aria-label={`${resolve(strings.moveDown)}: ${label}`}
                  disabled={index === columns.length - 1}
                  onClick={() => onMoveColumn(column.id, 1)}
                  style={reorderButtonStyle(index === columns.length - 1)}
                >
                  <ArrowDownGlyph size={14} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </DataViewMenu>
  );
}

function reorderButtonStyle(disabled: boolean) {
  return {
    display: "inline-flex",
    padding: "var(--space-1)",
    background: "transparent",
    border: "none",
    borderRadius: "var(--radius-sm)",
    cursor: disabled ? "not-allowed" : "pointer",
    color: disabled ? "var(--color-neutral-300)" : "var(--color-neutral-700)",
  } as const;
}
