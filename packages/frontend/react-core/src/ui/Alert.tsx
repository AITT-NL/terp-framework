import type { CSSProperties, ReactNode } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import type { BadgeTone } from "./Badge";

export type AlertTone = BadgeTone;

export interface AlertProps {
  tone?: AlertTone;
  title?: UiText;
  children: ReactNode;
}

const toneColor: Record<AlertTone, string> = {
  neutral: "var(--color-neutral-600)",
  info: "var(--color-status-info)",
  success: "var(--color-status-success)",
  warning: "var(--color-status-warning)",
  danger: "var(--color-status-danger)",
};

const toneSoft: Record<AlertTone, string> = {
  neutral: "var(--color-neutral-50)",
  info: "var(--color-status-info-soft)",
  success: "var(--color-status-success-soft)",
  warning: "var(--color-status-warning-soft)",
  danger: "var(--color-status-danger-soft)",
};

const alertStyle = (tone: AlertTone): CSSProperties => ({
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: "var(--space-3)",
  padding: "var(--space-3) var(--space-4)",
  border: `1px solid ${toneColor[tone]}`,
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-900)",
  background: toneSoft[tone],
});

const iconWrapStyle = (tone: AlertTone): CSSProperties => ({
  color: toneColor[tone],
  display: "inline-flex",
  alignItems: "flex-start",
  paddingTop: "2px",
});

const bodyStyle: CSSProperties = { display: "grid", gap: "var(--space-1)", minWidth: 0 };
const titleStyle: CSSProperties = { fontWeight: "var(--font-weight-semibold)" as never };

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

/** Inline banner for persistent feedback; warnings and errors announce as alerts. */
export function Alert({ tone = "info", title, children }: AlertProps) {
  const resolve = useUiText();
  return (
    <div
      role={tone === "warning" || tone === "danger" ? "alert" : "status"}
      data-terp="alert"
      style={alertStyle(tone)}
    >
      <span style={iconWrapStyle(tone)}>{toneIcon[tone]}</span>
      <div style={bodyStyle}>
        {title !== undefined && <strong style={titleStyle}>{resolve(title)}</strong>}
        <div>{children}</div>
      </div>
    </div>
  );
}

