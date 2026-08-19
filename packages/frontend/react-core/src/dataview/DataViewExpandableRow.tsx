import type { ReactNode } from "react";

import { ChevronDownGlyph, ChevronRightGlyph } from "./glyphs";
import { useDataViewText } from "./internal";

/**
 * The expand-toggle chevron rendered in the expand system column (and on cards).
 * Stops click propagation so toggling never triggers row navigation.
 */
export function DataViewExpandToggle({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  const { strings, resolve } = useDataViewText();
  return (
    <button
      type="button"
      aria-label={resolve(expanded ? strings.collapseRow : strings.expandRow)}
      aria-expanded={expanded}
      data-terp="iconbutton"
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
    >
      {expanded ? <ChevronDownGlyph /> : <ChevronRightGlyph />}
    </button>
  );
}

/**
 * The full-width detail panel row rendered directly under an expanded row: one cell
 * spanning every column, visually attached to its parent row.
 */
export function DataViewExpandableRow({
  colSpan,
  children,
}: {
  colSpan: number;
  children: ReactNode;
}) {
  return (
    <tr>
      <td colSpan={colSpan} data-terp="dataview-expanded-cell">
        {children}
      </td>
    </tr>
  );
}
