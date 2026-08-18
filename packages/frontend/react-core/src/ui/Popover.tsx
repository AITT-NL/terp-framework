import { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactElement, ReactNode } from "react";
import { createPortal } from "react-dom";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type PopoverPlacement = "bottom" | "top";
export type PopoverAlign = "start" | "end";

/**
 * The `data-terp` marker a Popover stamps on its rendered root.
 *
 * Three components in the package return a bare `Menu`, whose rendered root is this
 * wrapper — so their root was indistinguishable from any other popover, and none of them
 * could be styled or found. Threading the name through is what lets each say what it is
 * without adding an element to anybody's layout.
 *
 * A closed union rather than `string`, because a marker is framework vocabulary: every value
 * here needs a rule in the sheet and a line in the inventory, and the type says so before a
 * test has to.
 */
export type PopoverRootMarker = "popover" | "theme-toggle" | "language-switcher" | "user-menu";

/** Separates the variants of a component whose root is a Popover. */
export type PopoverRootVariant = "inline" | "stacked" | "collapsed";

export interface PopoverProps {
  trigger: ReactElement;
  children: (api: { close: (restoreFocus?: boolean) => void; panelId: string }) => ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: PopoverPlacement;
  align?: PopoverAlign;
  focusOnOpen?: boolean;
  /**
   * Override the root's marker, for a component whose rendered root this wrapper IS.
   * Named for the attribute it becomes, which is also what keeps the marker inventory
   * honest — the scanner reads `data-terp` sites in component source, so a consumer
   * writing `data-terp="user-menu"` is seen, while a `rootMarker` prop would not be.
   */
  "data-terp"?: PopoverRootMarker;
  /** Distinguishes that component's variants on the same root. */
  "data-variant"?: PopoverRootVariant;
  /**
   * Who owns the portalled panel, for a panel rule that has to reach it.
   *
   * Separate from `data-terp` on purpose. The root marker is necessarily CONDITIONAL — a
   * component whose stacked variant renders its own div must not stamp the marker on the
   * nested menu as well — so deriving the owner from it made the same component's panel
   * `theme-toggle` in one variant and `popover` in the other. A panel rule would then reach
   * one variant and silently miss the other, which is the failure mode the root selector
   * list two doors down exists to warn about. Defaults to the root marker for callers who
   * have no panel rule and do not care.
   */
  "data-owner"?: string;
}

const VIEWPORT_GUTTER = 8;
const PANEL_GAP = 4;

interface PanelPosition {
  left: number;
  top: number;
  visibility: CSSProperties["visibility"];
}

/** Anchored disclosure panel with outside-click, Escape close and focus return. */
export function Popover({
  trigger,
  children,
  open,
  defaultOpen = false,
  onOpenChange,
  placement = "bottom",
  align = "end",
  focusOnOpen = false,
  "data-terp": rootMarker,
  "data-variant": rootVariant,
  "data-owner": owner,
}: PopoverProps) {
  const panelId = useId();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const isOpen = open ?? uncontrolledOpen;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [panelPosition, setPanelPosition] = useState<PanelPosition>({
    left: 0,
    top: 0,
    visibility: "hidden",
  });

  const setOpen = useCallback(
    (next: boolean) => {
      if (open === undefined) {
        setUncontrolledOpen(next);
      }
      onOpenChange?.(next);
    },
    [onOpenChange, open],
  );

  const close = useCallback(
    (restoreFocus = true) => {
      setOpen(false);
      if (restoreFocus) {
        triggerRef.current?.focus();
      }
    },
    [setOpen],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    if (focusOnOpen) {
      window.setTimeout(() => {
        const first = panelRef.current?.querySelector<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        );
        (first ?? panelRef.current)?.focus();
      }, 0);
    }
    function onPointerDown(event: PointerEvent) {
      const root = rootRef.current;
      const panel = panelRef.current;
      if (
        root !== null &&
        event.target instanceof Node &&
        !root.contains(event.target) &&
        !panel?.contains(event.target)
      ) {
        close(false);
      }
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close(true);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [close, focusOnOpen, isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }
    function updatePosition() {
      const trigger = triggerRef.current;
      const panel = panelRef.current;
      if (trigger === null || panel === null) {
        return;
      }
      const anchor = trigger.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      const below = anchor.bottom + PANEL_GAP;
      const above = anchor.top - panelRect.height - PANEL_GAP;
      const preferredTop = placement === "bottom" ? below : above;
      const fallbackTop = placement === "bottom" ? above : below;
      const fitsPreferred = preferredTop >= VIEWPORT_GUTTER &&
        preferredTop + panelRect.height <= window.innerHeight - VIEWPORT_GUTTER;
      const rawTop = fitsPreferred ? preferredTop : fallbackTop;
      const rawLeft = align === "end"
        ? anchor.right - panelRect.width
        : anchor.left;
      setPanelPosition({
        left: Math.max(
          VIEWPORT_GUTTER,
          Math.min(rawLeft, window.innerWidth - panelRect.width - VIEWPORT_GUTTER),
        ),
        top: Math.max(
          VIEWPORT_GUTTER,
          Math.min(rawTop, window.innerHeight - panelRect.height - VIEWPORT_GUTTER),
        ),
        visibility: "visible",
      });
    }
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [align, isOpen, placement]);

  const triggerProps = trigger.props as Record<string, unknown>;
  const cloned = cloneElement(trigger, {
    ref: (node: HTMLElement | null) => {
      triggerRef.current = node;
      const originalRef = (trigger as ReactElement & { ref?: React.Ref<HTMLElement> }).ref;
      if (typeof originalRef === "function") {
        originalRef(node);
      } else if (originalRef && typeof originalRef === "object") {
        (originalRef as React.MutableRefObject<HTMLElement | null>).current = node;
      }
    },
    "aria-expanded": isOpen,
    "aria-controls": isOpen ? panelId : undefined,
    onClick: (event: MouseEvent) => {
      (triggerProps.onClick as ((event: MouseEvent) => void) | undefined)?.(event);
      if (!event.defaultPrevented) {
        setOpen(!isOpen);
      }
    },
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      (triggerProps.onKeyDown as ((event: KeyboardEvent<HTMLElement>) => void) | undefined)?.(event);
      if (!event.defaultPrevented && (event.key === "ArrowDown" || event.key === "ArrowUp") && !isOpen) {
        event.preventDefault();
        setOpen(true);
      }
    },
  } as Partial<typeof trigger.props>);

  return (
    <div ref={rootRef} data-terp={rootMarker ?? "popover"} data-variant={rootVariant}>
      {cloned}
      {isOpen && createPortal(
        <div
          id={panelId}
          ref={panelRef}
          data-terp="popover-panel"
          // Whose panel this is. The panel is portalled to document.body, so a descendant
          // selector rooted at the trigger's side of the tree cannot reach it — and a
          // per-caller panel geometry therefore has nowhere to hang unless the panel itself
          // says who owns it. This is what replaced the `panelStyle` prop: the owner's rule
          // lives in the sheet with everything else instead of travelling as an object.
          data-owner={owner ?? rootMarker ?? "popover"}
          tabIndex={-1}
          // Only the measured part is inline: the left/top the layout effect computes from
          // the trigger's rect and clamps against the viewport, and the visibility that
          // hides the panel for the frame before that measurement exists. Everything the
          // panel LOOKS like is a rule (ADR 0094).
          style={panelPosition}
        >
          {children({ close, panelId })}
        </div>,
        document.body,
      )}
    </div>
  );
}
