import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

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

/**
 * Soft tint per tone — exported (not via the package barrel) so DataView's row/card
 * tinting resolves a tone to the exact same tokens the Badge pill uses.
 *
 * The pill itself no longer reads this map: its tones are rules in the sheet, keyed on
 * `data-tone` (ADR 0094). It stays because DataView tints rows and cards from an inline
 * background and still needs the tone-to-token mapping; that call site is the one that
 * removes this export, when the DataView cluster migrates.
 */
export const toneSoftColors: Record<BadgeTone, string> = {
  neutral: "var(--color-neutral-100)",
  info: "var(--color-status-info-soft)",
  success: "var(--color-status-success-soft)",
  warning: "var(--color-status-warning-soft)",
  danger: "var(--color-status-danger-soft)",
};

/** Small token-styled status pill — flat soft tint with a matching text colour. */
export function Badge({ label, children, tone = "neutral" }: BadgeProps) {
  const resolve = useUiText();
  return (
    <span data-terp="badge" data-tone={tone}>
      {resolve((label ?? children) as UiText)}
    </span>
  );
}

