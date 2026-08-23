import { cloneElement, isValidElement, useEffect, useId, useRef, useState } from "react";
import type { FocusEvent, MouseEvent, ReactElement } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

export interface TooltipProps {
  content: UiText;
  children: ReactElement;
  /**
   * Start with the bubble shown.
   *
   * The same dev/specimen affordance `AppShell.defaultCollapsed` and `defaultDrawerOpen` are,
   * added for the same reason: the panel's whole style block — its surface, its ink, its shadow
   * and its measure — was painted by nothing. The one Tooltip specimen renders the trigger with
   * the bubble closed, and neither browser lane can hover or focus, so a change to any of those
   * declarations moved no pixel that any gate reads. An app has no reason to pin a tooltip open.
   */
  defaultOpen?: boolean;
}

interface TriggerHandlers {
  onFocus?: (event: FocusEvent) => void;
  onBlur?: (event: FocusEvent) => void;
  onMouseEnter?: (event: MouseEvent) => void;
  onMouseLeave?: (event: MouseEvent) => void;
  "aria-describedby"?: string;
}

/**
 * Accessible focus/hover tooltip.
 *
 * Holds all three parts of WCAG 1.4.13 (Content on Hover or Focus, level AA), and two of them
 * had to be added:
 *
 * - **Dismissible.** Escape closes the bubble without moving the pointer or focus. There was no
 *   key handler of any kind before, so a tooltip covering the content beneath it could only be
 *   escaped by moving away from the control the user was reading about.
 * - **Hoverable.** The bubble is reachable with the pointer. It used to declare
 *   `pointer-events: none`, which makes hovering it impossible by construction — so a tooltip
 *   long enough to need reading could not be read by anyone tracking with a pointer or using
 *   magnification. The bubble is a DOM child of the anchor, so moving onto it does not fire the
 *   anchor's `mouseleave`; the close delay below covers the visual gap between the two, which
 *   the pointer does cross.
 * - **Persistent.** It stays until dismissed, focus leaves or the pointer leaves — it has never
 *   had a timeout.
 */
export function Tooltip({ content, children, defaultOpen = false }: TooltipProps) {
  const id = useId();
  const resolve = useUiText();
  const [open, setOpen] = useState(defaultOpen);
  // Cleared on re-entry, which is what makes the gap between trigger and bubble crossable.
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function cancelClose() {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function scheduleClose() {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  }

  useEffect(() => cancelClose, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    // On the document rather than the trigger: the pointer-opened case has no focus anywhere
    // near this component, so a handler bound to the trigger would never see the key. The same
    // placement Popover uses, for the same reason.
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!isValidElement<TriggerHandlers>(children)) {
    return children;
  }

  return (
    <span
      data-terp="tooltip-anchor"
      onMouseEnter={() => {
        cancelClose();
        setOpen(true);
      }}
      onMouseLeave={scheduleClose}
    >
      {cloneElement(children, {
        "aria-describedby": id,
        onFocus: (event: FocusEvent) => {
          children.props.onFocus?.(event);
          cancelClose();
          setOpen(true);
        },
        onBlur: (event: FocusEvent) => {
          children.props.onBlur?.(event);
          setOpen(false);
        },
      })}
      <span id={id} role="tooltip" data-terp="tooltip" hidden={!open}>
        {resolve(content)}
      </span>
    </span>
  );
}
