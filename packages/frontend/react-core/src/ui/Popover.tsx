import { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactElement, ReactNode } from "react";
import { createPortal } from "react-dom";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type PopoverPlacement = "bottom" | "top";
export type PopoverAlign = "start" | "end";

export interface PopoverProps {
  trigger: ReactElement;
  children: (api: { close: (restoreFocus?: boolean) => void; panelId: string }) => ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: PopoverPlacement;
  align?: PopoverAlign;
  focusOnOpen?: boolean;
  panelStyle?: CSSProperties;
}

const rootStyle: CSSProperties = { position: "relative", display: "inline-flex" };

const basePanelStyle: CSSProperties = {
  position: "fixed",
  zIndex: 60,
  minWidth: "12rem",
  padding: "var(--space-1)",
  fontFamily: "var(--font-family-sans)",
  color: "var(--color-neutral-900)",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-lg)",
};

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
  panelStyle,
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
    <div ref={rootRef} data-terp="popover" style={rootStyle}>
      {cloned}
      {isOpen && createPortal(
        <div
          id={panelId}
          ref={panelRef}
          data-terp="popover-panel"
          tabIndex={-1}
          style={{ ...basePanelStyle, ...panelStyle, ...panelPosition }}
        >
          {children({ close, panelId })}
        </div>,
        document.body,
      )}
    </div>
  );
}
