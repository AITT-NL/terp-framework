import { cloneElement, isValidElement, useId, useState } from "react";
import type { FocusEvent, MouseEvent, ReactElement } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

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
    <span
      data-terp="tooltip-anchor"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
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
      <span id={id} role="tooltip" data-terp="tooltip" hidden={!open}>
        {resolve(content)}
      </span>
    </span>
  );
}
