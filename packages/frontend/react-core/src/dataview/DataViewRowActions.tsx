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
}

function InlineActionButton<T>({ action, row }: { action: DataViewRowAction<T>; row: T }) {
  const { resolve } = useDataViewText();
  const disabled = resolveRowFlag(action.disabled, row);
  const destructive = action.variant === "destructive";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => action.onClick?.(row)}
      style={{
        font: "inherit",
        fontSize: "var(--font-size-sm)",
        display: "inline-flex",
        alignItems: "center",
        minHeight: "2rem",
        gap: "var(--space-1)",
        padding: "var(--space-1) var(--space-2)",
        background: "transparent",
        border: "1px solid var(--color-neutral-300)",
        borderRadius: "var(--radius-md)",
        cursor: disabled ? "not-allowed" : "pointer",
        color: disabled
          ? "var(--color-neutral-300)"
          : destructive
            ? "var(--color-status-danger)"
            : "var(--color-neutral-700)",
      }}
    >
      {action.icon !== undefined && (
        <span aria-hidden style={{ display: "inline-flex" }}>{action.icon}</span>
      )}
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
    <span key={`custom-${index}`} style={{ display: "inline-flex" }}>
      {action.render?.(row)}
    </span>
  );

  return (
    <span
      onClick={stop}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: "var(--space-1)",
      }}
    >
      {custom.map(renderCustom)}
      {inline.map((action, index) => (
        <InlineActionButton key={`inline-${index}`} action={action} row={row} />
      ))}
      {menu.length > 0 && (
        <DataViewMenu
          trigger={<EllipsisGlyph />}
          triggerLabel={resolve(strings.moreActions)}
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
