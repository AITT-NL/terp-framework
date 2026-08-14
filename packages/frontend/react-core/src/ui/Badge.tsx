import type { CSSProperties } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * The pill's content, either way round.
 *
 * Every other component in the catalog takes children, so `<Badge tone="success">No
 * drift</Badge>` is the obvious first guess — it used to be a typecheck error, for no
 * reason a caller could see. Both spellings work; `label` stays for call sites that
 * already use it, and either accepts a `UiText` so the string still translates.
 */
export type BadgeProps = { tone?: BadgeTone } & (
  | { label: UiText; children?: never }
  | { children: UiText; label?: never }
);

const toneColor: Record<BadgeTone, string> = {
  neutral: "var(--color-neutral-600)",
  info: "var(--color-status-info)",
  success: "var(--color-status-success)",
  warning: "var(--color-status-warning)",
  danger: "var(--color-status-danger)",
};

/**
 * Soft tint per tone — exported (not via the package barrel) so DataView's row/card
 * tinting resolves a tone to the exact same tokens the Badge pill uses.
 */
export const toneSoftColors: Record<BadgeTone, string> = {
  neutral: "var(--color-neutral-100)",
  info: "var(--color-status-info-soft)",
  success: "var(--color-status-success-soft)",
  warning: "var(--color-status-warning-soft)",
  danger: "var(--color-status-danger-soft)",
};

const badgeStyle = (tone: BadgeTone): CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  border: `1px solid ${toneSoftColors[tone]}`,
  borderRadius: "var(--radius-full)",
  padding: "2px var(--space-2)",
  color: toneColor[tone],
  background: toneSoftColors[tone],
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-semibold)" as never,
  lineHeight: 1.4,
  whiteSpace: "nowrap",
});

/** Small token-styled status pill — flat soft tint with a matching text colour. */
export function Badge({ label, children, tone = "neutral" }: BadgeProps) {
  const resolve = useUiText();
  return <span style={badgeStyle(tone)}>{resolve((label ?? children) as UiText)}</span>;
}

