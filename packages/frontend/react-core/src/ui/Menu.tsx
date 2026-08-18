import { useRef } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";

import { Icon } from "../icons";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { Popover } from "./Popover";
import type { PopoverAlign, PopoverPlacement, PopoverRootMarker, PopoverRootVariant } from "./Popover";

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
  /**
   * Name this menu's rendered root — which is Popover's wrapper, since a Menu adds no root
   * element of its own. `ThemeToggle`, `LanguageSwitcher` and `UserMenu` each return a bare
   * Menu, so without this their roots all read `data-terp="popover"`.
   */
  "data-terp"?: PopoverRootMarker;
  /** Distinguishes that component's variants on the same root. */
  "data-variant"?: PopoverRootVariant;
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
  "data-terp": rootMarker,
  "data-variant": rootVariant,
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
      data-terp={rootMarker}
      data-variant={rootVariant}
      trigger={
        // Its own marker rather than the shared `iconbutton` it used to borrow. That marker
        // is worn by seven visually different buttons — the shell's two header toggles, four
        // pagination arrows, a toast dismisser, the combobox's clear button and the calendar's
        // month arrows — and it has no base rule at all, because each is styled by where it
        // sits. This one is an outlined control with a border, a radius and control
        // typography, and it is also the trigger whose root marker is about to become
        // configurable, so a `[data-terp="popover"] > [data-terp="iconbutton"]` structural
        // rule would have to grow a branch per root name and would silently stop matching
        // the day one was added. A name of its own has neither problem.
        <button
          type="button"
          data-terp="menu-trigger"
          aria-label={resolve(triggerLabel)}
          aria-haspopup="menu"
          style={triggerStyleOverride}
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
      // Destructive is an enumerable choice, so it becomes an attribute. Disabled is not:
      // this is a real <button> carrying the real disabled attribute, so :disabled already
      // says it and inventing data-disabled beside it would be a second source of truth.
      data-destructive={destructive ? "true" : undefined}
      tabIndex={-1}
      disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onSelect();
        }
      }}
    >
      {icon !== undefined && (
        <span aria-hidden="true" data-terp="menu-item-icon">
          {icon}
        </span>
      )}
      {resolve(label)}
      {selected === true && (
        <span aria-hidden="true" data-terp="menu-item-check">
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
