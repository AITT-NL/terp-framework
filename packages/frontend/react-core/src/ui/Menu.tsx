import { useRef } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";

import { Icon } from "../icons";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { CONTROL_TEXT_STYLE } from "./controlStyles";
import { Popover } from "./Popover";
import type { PopoverAlign, PopoverPlacement } from "./Popover";

const triggerStyle: CSSProperties = {
  ...CONTROL_TEXT_STYLE,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minHeight: "2rem",
  gap: "var(--space-1)",
  padding: "var(--space-1) var(--space-2)",
  background: "transparent",
  color: "var(--color-neutral-700)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
};

const menuStyle: CSSProperties = { display: "grid", gap: "var(--space-1)" };

const itemStyle = (destructive: boolean, disabled: boolean): CSSProperties => ({
  ...CONTROL_TEXT_STYLE,
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  width: "100%",
  padding: "var(--space-2)",
  background: "transparent",
  border: "none",
  borderRadius: "var(--radius-sm)",
  textAlign: "left",
  justifyContent: "flex-start",
  cursor: disabled ? "not-allowed" : "pointer",
  color: disabled
    ? "var(--color-neutral-300)"
    : destructive
      ? "var(--color-status-danger)"
      : "var(--color-neutral-900)",
});

export interface MenuProps {
  trigger: ReactNode;
  triggerLabel: UiText;
  children: (api: { close: (restoreFocus?: boolean) => void }) => ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  align?: PopoverAlign;
  placement?: PopoverPlacement;
  triggerStyle?: CSSProperties;
  panelStyle?: CSSProperties;
}

/** Dropdown menu built on Popover with roving focus and ARIA menu semantics. */
export function Menu({
  trigger,
  triggerLabel,
  children,
  open,
  defaultOpen,
  onOpenChange,
  align = "end",
  placement = "bottom",
  triggerStyle: triggerStyleOverride,
  panelStyle,
}: MenuProps) {
  const resolve = useUiText();
  const menuRef = useRef<HTMLDivElement>(null);

  function focusItem(direction: 1 | -1 | "first" | "last") {
    const items = menuItems(menuRef.current).filter((item) => !item.disabled);
    if (items.length === 0) {
      return;
    }
    const currentIndex = items.findIndex((item) => item === document.activeElement);
    const nextIndex = direction === "first"
      ? 0
      : direction === "last"
        ? items.length - 1
        : currentIndex < 0
          ? 0
          : (currentIndex + direction + items.length) % items.length;
    items[nextIndex]?.focus();
  }

  return (
    <Popover
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      align={align}
      placement={placement}
      panelStyle={panelStyle}
      trigger={
        <button
          type="button"
          data-terp="iconbutton"
          aria-label={resolve(triggerLabel)}
          aria-haspopup="menu"
          style={{ ...triggerStyle, ...triggerStyleOverride }}
        >
          {trigger}
        </button>
      }
    >
      {({ close }) => (
        <div
          ref={(node) => {
            menuRef.current = node;
            if (node !== null && !node.contains(document.activeElement)) {
              menuItems(node).find((item) => !item.disabled)?.focus();
            }
          }}
          role="menu"
          data-terp="menu"
          style={menuStyle}
          onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
            switch (event.key) {
              case "Escape":
                event.preventDefault();
                close(true);
                break;
              case "ArrowDown":
                event.preventDefault();
                focusItem(1);
                break;
              case "ArrowUp":
                event.preventDefault();
                focusItem(-1);
                break;
              case "Home":
                event.preventDefault();
                focusItem("first");
                break;
              case "End":
                event.preventDefault();
                focusItem("last");
                break;
              case "Tab":
                close(false);
                break;
              default:
                break;
            }
          }}
        >
          {children({ close })}
        </div>
      )}
    </Popover>
  );
}


export interface MenuItemProps {
  label: UiText;
  icon?: ReactNode;
  /** Marks one choice in a mutually exclusive menu (renders `menuitemradio`). */
  selected?: boolean;
  destructive?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

/** One actionable item inside a Menu. */
export function MenuItem({
  label,
  icon,
  selected,
  destructive = false,
  disabled = false,
  onSelect,
}: MenuItemProps) {
  const resolve = useUiText();
  return (
    <button
      type="button"
      role={selected === undefined ? "menuitem" : "menuitemradio"}
      aria-checked={selected}
      data-terp="menu-item"
      data-selected={selected === true ? "true" : undefined}
      tabIndex={-1}
      disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onSelect();
        }
      }}
      style={itemStyle(destructive, disabled)}
    >
      {icon !== undefined && <span aria-hidden="true" style={{ display: "inline-flex" }}>{icon}</span>}
      {resolve(label)}
      {selected === true && (
        <span aria-hidden="true" style={{ display: "inline-flex", marginLeft: "auto" }}>
          <Icon name="check" />
        </span>
      )}
    </button>
  );
}

function menuItems(menu: HTMLDivElement | null): HTMLButtonElement[] {
  if (menu === null) {
    return [];
  }
  return Array.from(
    menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"], [role="menuitemradio"]'),
  );
}
