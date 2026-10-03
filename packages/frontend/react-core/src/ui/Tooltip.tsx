import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { CSSProperties, FocusEvent, MouseEvent, ReactElement } from "react";
import { createPortal } from "react-dom";

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

/** The bubble never comes closer than this to the window's edge. Popover's value. */
const VIEWPORT_GUTTER = 8;
/** Between the trigger and the bubble: the var(--space-1) the sheet used to offset it by. */
const BUBBLE_GAP = 4;

interface BubblePosition {
  left: number;
  top: number;
  visibility: CSSProperties["visibility"];
}

const UNPLACED: BubblePosition = { left: 0, top: 0, visibility: "hidden" };

/**
 * Where the bubble goes: above the trigger if it fits there, below if it does not, and inside
 * the window either way. Start-aligned with the trigger, as the sheet placed it before -- the
 * trigger's left edge, or its right one in a right-to-left document -- and pushed back in from
 * whichever edge it would cross. Exported for its tests, not from the package.
 */
export function placeBubble(
  trigger: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
  bubble: Pick<DOMRect, "width" | "height">,
  viewport: { width: number; height: number },
  rtl = false,
): Pick<BubblePosition, "left" | "top"> {
  const above = trigger.top - BUBBLE_GAP - bubble.height;
  const below = trigger.bottom + BUBBLE_GAP;
  const fitsAbove = above >= VIEWPORT_GUTTER;
  const fitsBelow = below + bubble.height <= viewport.height - VIEWPORT_GUTTER;
  // Above is the preference; below only when above does not fit and below does. With room in
  // neither (a very short window), above is clamped to the top edge and covers the trigger,
  // which is still readable, where off-screen is not.
  const rawTop = fitsAbove || !fitsBelow ? above : below;
  const rawLeft = rtl ? trigger.right - bubble.width : trigger.left;
  return {
    left: Math.max(
      VIEWPORT_GUTTER,
      Math.min(rawLeft, viewport.width - bubble.width - VIEWPORT_GUTTER),
    ),
    top: Math.max(
      VIEWPORT_GUTTER,
      Math.min(rawTop, viewport.height - bubble.height - VIEWPORT_GUTTER),
    ),
  };
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
 *   magnification. The bubble is portalled, but React dispatches enter and leave along the
 *   component tree rather than the DOM, where the bubble is still the anchor's child — so
 *   moving onto it does not fire the anchor's `mouseleave`. The close delay below covers the
 *   visual gap between the two, which the pointer does cross.
 * - **Persistent.** It stays until dismissed, focus leaves or the pointer leaves — it has never
 *   had a timeout.
 *
 * And it is readable wherever its trigger is. The bubble is portalled to the body -- or into the
 * dialog its trigger sits in, since nothing outside a modal dialog paints above it -- and placed
 * from measured coordinates (see the sheet's tooltip rule for the three ways the absolutely
 * positioned version was not): no scroll container clips it, its width is the message's
 * rather than the trigger's, and it flips below a trigger too close to the top and stays
 * inside the window at the sides.
 */
export function Tooltip({ content, children, defaultOpen = false }: TooltipProps) {
  const id = useId();
  const resolve = useUiText();
  const [open, setOpen] = useState(defaultOpen);
  // Resolved once, and a dependency of the placement below: text that changes while the
  // bubble is open ("Copy" becoming "Copied to clipboard") changes its size, and a bubble
  // placed for the old size runs past the window's edge or over its trigger.
  const text = resolve(content);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<BubblePosition>(UNPLACED);
  // Where the bubble is portalled to, known only once mounted: a server render has no body,
  // and the first client render has to produce what the server did.
  const [host, setHost] = useState<HTMLElement | null>(null);
  // Cleared on re-entry, which is what makes the gap between trigger and bubble crossable.
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // The trigger's own <dialog> when it sits in one, and the body otherwise. A modal dialog
    // is in the top layer, and nothing outside it paints above it or its backdrop whatever
    // its z-index: a bubble portalled to the body opened BEHIND the dialog its trigger was in.
    // Measured in Chromium: a fixed box inside a modal dialog, outside the dialog's own box,
    // is the topmost element at its point (the dialog's overflow: auto does not clip it, since
    // a fixed box is placed against the viewport), and the same box under the body at
    // z-index 70 is covered by the backdrop.
    setHost(anchorRef.current?.closest("dialog") ?? document.body);
  }, []);

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

  // Measured before paint, so an open bubble is never painted where it was last time; the
  // first open is painted nowhere until this has run (UNPLACED is visibility: hidden). Kept up
  // to date while open, because a fixed bubble does not move with a scrolled trigger.
  useLayoutEffect(() => {
    if (!open || host === null) {
      return;
    }
    function update() {
      const anchor = anchorRef.current;
      const bubble = bubbleRef.current;
      if (anchor === null || bubble === null) {
        return;
      }
      // The root's client box rather than the window's inner size: innerWidth includes a
      // classic vertical scrollbar, so a bubble pushed in from the right edge by it could
      // still sit partly under the bar. A document with no layout reports 0 here, and the
      // window's size is the honest answer then.
      const root = document.documentElement;
      const { left, top } = placeBubble(
        anchor.getBoundingClientRect(),
        bubble.getBoundingClientRect(),
        {
          width: root.clientWidth || window.innerWidth,
          height: root.clientHeight || window.innerHeight,
        },
        getComputedStyle(anchor).direction === "rtl",
      );
      setPosition({ left, top, visibility: "visible" });
    }
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, host, text]);

  if (!isValidElement<TriggerHandlers>(children)) {
    return children;
  }

  const bubble = (
    <span
      ref={bubbleRef}
      id={id}
      role="tooltip"
      data-terp="tooltip"
      hidden={!open}
      // Only the measured part is inline -- the coordinates and the visibility that hides the
      // bubble for the frame before they exist. Everything it LOOKS like is the sheet's.
      style={position}
    >
      {text}
    </span>
  );

  return (
    <span
      ref={anchorRef}
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
      {host !== null && createPortal(bubble, host)}
    </span>
  );
}
