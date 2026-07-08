import type { CSSProperties } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface BadgeProps {
  label: UiText;
  tone?: BadgeTone;
}

const toneColor: Record<BadgeTone, string> = {
  neutral: "var(--color-neutral-600)",
  info: "var(--color-status-info)",
  success: "var(--color-status-success)",
  warning: "var(--color-status-warning)",
  danger: "var(--color-status-danger)",
};

const toneSoft: Record<BadgeTone, string> = {
  neutral: "var(--color-neutral-100)",
  info: "var(--color-status-info-soft)",
  success: "var(--color-status-success-soft)",
  warning: "var(--color-status-warning-soft)",
  danger: "var(--color-status-danger-soft)",
};

const badgeStyle = (tone: BadgeTone): CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  border: `1px solid ${toneSoft[tone]}`,
  borderRadius: "var(--radius-full)",
  padding: "2px var(--space-2)",
  color: toneColor[tone],
  background: toneSoft[tone],
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-semibold)" as never,
  lineHeight: 1.4,
  whiteSpace: "nowrap",
});

/** Small token-styled status pill — flat soft tint with a matching text colour. */
export function Badge({ label, tone = "neutral" }: BadgeProps) {
  const resolve = useUiText();
  return <span style={badgeStyle(tone)}>{resolve(label)}</span>;
}

