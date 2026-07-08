import { cloneElement, isValidElement, useId, useState } from "react";
import type { CSSProperties, FocusEvent, MouseEvent, ReactElement } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

const wrapperStyle: CSSProperties = { position: "relative", display: "inline-flex" };
const tooltipStyle: CSSProperties = {
  position: "absolute",
  zIndex: 1,
  insetBlockEnd: "calc(100% + var(--space-1))",
  insetInlineStart: 0,
  maxInlineSize: "min(18rem, calc(100vw - 2 * var(--space-4)))",
  padding: "var(--space-1) var(--space-2)",
  borderRadius: "var(--radius-sm)",
  color: "var(--color-neutral-0)",
  background: "var(--color-neutral-900)",
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-medium)" as never,
  lineHeight: 1.4,
  boxShadow: "var(--shadow-md)",
  pointerEvents: "none",
  whiteSpace: "normal",
};

export interface TooltipProps {
  content: UiText;
  children: ReactElement;
}

interface TriggerHandlers {
  onFocus?: (event: FocusEvent) => void;
  onBlur?: (event: FocusEvent) => void;
  onMouseEnter?: (event: MouseEvent) => void;
  onMouseLeave?: (event: MouseEvent) => void;
  "aria-describedby"?: string;
}

/** Accessible focus/hover tooltip. */
export function Tooltip({ content, children }: TooltipProps) {
  const id = useId();
  const resolve = useUiText();
  const [open, setOpen] = useState(false);

  if (!isValidElement<TriggerHandlers>(children)) {
    return children;
  }

  return (
    <span style={wrapperStyle} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      {cloneElement(children, {
        "aria-describedby": id,
        onFocus: (event: FocusEvent) => {
          children.props.onFocus?.(event);
          setOpen(true);
        },
        onBlur: (event: FocusEvent) => {
          children.props.onBlur?.(event);
          setOpen(false);
        },
      })}
      <span id={id} role="tooltip" hidden={!open} style={tooltipStyle}>
        {resolve(content)}
      </span>
    </span>
  );
}
