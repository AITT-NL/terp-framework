import type { ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import type { BadgeTone } from "./Badge";

injectTerpStyles();

export type AlertTone = BadgeTone;

export interface AlertProps {
  tone?: AlertTone;
  title?: UiText;
  children: ReactNode;
}

const glyphProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
} as const;

const toneIcon: Record<AlertTone, ReactNode> = {
  neutral: (
    <svg {...glyphProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01M11 12h1v5h1" />
    </svg>
  ),
  info: (
    <svg {...glyphProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01M11 12h1v5h1" />
    </svg>
  ),
  success: (
    <svg {...glyphProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </svg>
  ),
  warning: (
    <svg {...glyphProps}>
      <path d="M12 3 2.5 20.5h19L12 3Z" />
      <path d="M12 10v5M12 18h.01" />
    </svg>
  ),
  danger: (
    <svg {...glyphProps}>
      <path d="M17.5 3.5H6.5L3 7v10l3.5 3.5h11L21 17V7l-3.5-3.5Z" />
      <path d="M12 8v5M12 16h.01" />
    </svg>
  ),
};

/**
 * Inline banner for persistent feedback; warnings and errors announce as alerts.
 *
 * The tone is a `data-tone` attribute rather than a style object: the sheet paints the
 * frame, the tint and the glyph from it, and the body restates the reading colour so the
 * copy stays neutral while the frame carries the tone (ADR 0094).
 */
export function Alert({ tone = "info", title, children }: AlertProps) {
  const resolve = useUiText();
  return (
    <div
      role={tone === "warning" || tone === "danger" ? "alert" : "status"}
      data-terp="alert"
      data-tone={tone}
    >
      <span data-terp="alert-icon">{toneIcon[tone]}</span>
      <div data-terp="alert-body">
        {title !== undefined && <strong data-terp="alert-title">{resolve(title)}</strong>}
        <div>{children}</div>
      </div>
    </div>
  );
}

