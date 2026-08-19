import type { MouseEvent, ReactNode } from "react";

import { EllipsisGlyph } from "./glyphs";
import { DataViewMenu, DataViewMenuItem, useDataViewText } from "./internal";
import type { DataViewRowAction } from "./types";
import { resolveRowFlag } from "./types";

export type DataViewRowActionsLayout = "menu" | "inline";

export interface DataViewRowActionsProps<T> {
  row: T;
  actions: DataViewRowAction<T>[];
  /** "menu" (default): ellipsis dropdown, `inline`-flagged actions beside it. */
  layout: DataViewRowActionsLayout;
  /** On mobile all standard actions collapse into the menu regardless of flags. */
  isMobile: boolean;
  /**
   * Render the overflow menu open on mount — the same escape `Menu`, `Popover` and both
   * date pickers already expose, and for the same reason: a portalled panel is invisible
   * to a per-specimen visual lane unless something can name its open state.
   */
  defaultOpen?: boolean;
}

function InlineActionButton<T>({ action, row }: { action: DataViewRowAction<T>; row: T }) {
  const { resolve } = useDataViewText();
  const disabled = resolveRowFlag(action.disabled, row);
  const destructive = action.variant === "destructive";
  return (
    <button
      type="button"
      data-terp="dataview-row-action"
      data-destructive={destructive || undefined}
      disabled={disabled}
      onClick={() => action.onClick?.(row)}
    >
      {action.icon !== undefined && <span aria-hidden>{action.icon}</span>}
      {resolve(action.label)}
    </button>
  );
}

/**
 * The per-row actions control: renders custom controls inline always, standard actions
 * either as buttons ("inline" layout / `inline` flag) or in an ellipsis menu. The whole
 * cluster stops click propagation so actions never trigger row navigation.
 */
export function DataViewRowActions<T>({
  row,
  actions,
  layout,
  isMobile,
  defaultOpen,
}: DataViewRowActionsProps<T>) {
  const { strings, resolve } = useDataViewText();

  const visible = actions.filter((action) => !resolveRowFlag(action.hidden, row));
  if (visible.length === 0) {
    return null;
  }

  // Custom controls always render inline and own their interaction surface.
  const custom = visible.filter((action) => action.render !== undefined);
  const standard = visible.filter((action) => action.render === undefined);
  const inline = isMobile
    ? []
    : layout === "inline"
      ? standard
      : standard.filter((action) => action.inline === true);
  const menu = standard.filter((action) => !inline.includes(action));

  const stop = (event: MouseEvent) => event.stopPropagation();

  const renderCustom = (action: DataViewRowAction<T>, index: number): ReactNode => (
    <span key={`custom-${index}`}>{action.render?.(row)}</span>
  );

  return (
    <span data-terp="dataview-row-actions" onClick={stop}>
      {custom.map(renderCustom)}
      {inline.map((action, index) => (
        <InlineActionButton key={`inline-${index}`} action={action} row={row} />
      ))}
      {menu.length > 0 && (
        <DataViewMenu
          trigger={<EllipsisGlyph />}
          triggerLabel={resolve(strings.moreActions)}
          defaultOpen={defaultOpen}
        >
          {(close) => (
            <>
              {menu.map((action, index) => (
                <DataViewMenuItem
                  key={index}
                  label={resolve(action.label)}
                  icon={action.icon}
                  destructive={action.variant === "destructive"}
                  disabled={resolveRowFlag(action.disabled, row)}
                  onSelect={() => {
                    close();
                    action.onClick?.(row);
                  }}
                />
              ))}
            </>
          )}
        </DataViewMenu>
      )}
    </span>
  );
}
