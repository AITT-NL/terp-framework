import { useId } from "react";

import { Popover } from "../ui/Popover";
import { ArrowDownGlyph, ArrowUpGlyph, ColumnsGlyph } from "./glyphs";
import { useDataViewText } from "./internal";
import type { DataViewColumn } from "./types";

export interface DataViewColumnSettingsProps<T> {
  /** The user columns in effective order (system columns are never listed here). */
  columns: DataViewColumn<T>[];
  columnVisibility: Record<string, boolean>;
  onColumnVisibleChange: (columnId: string, visible: boolean) => void;
  onMoveColumn: (columnId: string, direction: -1 | 1) => void;
  /**
   * Render the panel open on mount — the same escape the menu primitive already exposes,
   * and the only way a portalled panel reaches a per-specimen visual lane.
   */
  defaultOpen?: boolean;
}

/**
 * The "view options" panel: per-column show/hide checkboxes and up/down reordering.
 * Only user columns appear — the pinned system columns (select/expand/actions) are
 * never hideable or reorderable, and are skipped when computing reorder targets
 * because this list simply does not contain them.
 *
 * A `Popover` rather than a `Menu`, and the distinction is a correctness one rather than
 * a preference. `Menu` stamps `role="menu"`, which ARIA requires to own only
 * `menuitem` / `menuitemradio` / `menuitemcheckbox` / `group` children — and this panel's
 * content is a heading, labelled checkboxes and paired reorder buttons, which is a small
 * FORM. Feeding it to a menu produced a critical `aria-required-children` violation in
 * every theme, and there is no arrangement that fixes it while keeping the interaction:
 * reorder buttons inside a `menuitemcheckbox` would be interactive descendants of a menu
 * item, which ARIA forbids in turn. The panel is therefore a group labelled by its own
 * heading, navigated with Tab the way a form is, and `Popover` supplies the Escape,
 * outside-click and focus-return behaviour `Menu` was being used for.
 *
 * Nothing had rendered this panel open before, which is why a shipped critical defect was
 * invisible: the screenshot lane clips to the specimen and the panel portals to the body,
 * and no specimen opened it at all.
 */
export function DataViewColumnSettings<T>({
  columns,
  columnVisibility,
  onColumnVisibleChange,
  onMoveColumn,
  defaultOpen,
}: DataViewColumnSettingsProps<T>) {
  const { strings, resolve } = useDataViewText();
  const headingId = useId();

  return (
    <Popover
      defaultOpen={defaultOpen}
      focusOnOpen
      data-owner="dataview-column-settings"
      trigger={
        // The trigger keeps the menu-trigger marker, which is styling vocabulary rather than
        // a semantic claim — the sheet describes it as the package's outlined control, and
        // reusing it is what keeps this control's appearance identical. What it does NOT keep
        // is aria-haspopup="menu", because the panel is no longer a menu; Popover supplies
        // aria-expanded and aria-controls, which is the whole contract for a disclosure.
        <button type="button" data-terp="menu-trigger">
          <ColumnsGlyph />
          <span>{resolve(strings.viewOptions)}</span>
        </button>
      }
    >
      {() => (
        <div data-terp="dataview-column-settings" role="group" aria-labelledby={headingId}>
          <div id={headingId} data-terp="dataview-column-settings-title">
            {resolve(strings.columns)}
          </div>
          {columns.map((column, index) => {
            const label = resolve(column.meta?.label ?? column.header);
            const visible = columnVisibility[column.id] !== false;
            return (
              <div key={column.id} data-terp="dataview-column-option">
                <label>
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
                  data-terp="iconbutton"
                  aria-label={`${resolve(strings.moveUp)}: ${label}`}
                  disabled={index === 0}
                  onClick={() => onMoveColumn(column.id, -1)}
                >
                  <ArrowUpGlyph size={14} />
                </button>
                <button
                  type="button"
                  data-terp="iconbutton"
                  aria-label={`${resolve(strings.moveDown)}: ${label}`}
                  disabled={index === columns.length - 1}
                  onClick={() => onMoveColumn(column.id, 1)}
                >
                  <ArrowDownGlyph size={14} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </Popover>
  );
}
