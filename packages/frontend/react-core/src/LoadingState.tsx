import type { CSSProperties } from "react";

import { injectTerpStyles } from "./styles";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

export interface InlineSpinnerProps {
  /** Diameter in pixels; default 16. Inherits `currentColor`. */
  size?: number;
}

/**
 * Compact inline loading spinner for table cells, buttons, and tight layouts —
 * just the spinning glyph, no label (it is hidden from assistive tech). Use
 * {@link LoadingState} for a full loading block that announces itself.
 * Rendered as an SVG so react-core takes no icon dependency; the rotation uses
 * a CSS animation (respects `prefers-reduced-motion`).
 */
export function InlineSpinner({ size = 16 }: InlineSpinnerProps) {
  return (
    <span
      aria-hidden="true"
      data-terp="spinner-ring"
      style={{
        display: "inline-block",
        verticalAlign: "middle",
        width: size,
        height: size,
        lineHeight: 0,
      }}
    >
      <svg
        aria-hidden="true"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        style={{ display: "block" }}
      >
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeOpacity="0.2"
          strokeWidth="3"
        />
        <path
          d="M12 2a10 10 0 0 1 10 10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export interface LoadingStateProps {
  /** Short description of what is loading; defaults to the `loading` string. */
  label?: UiText;
}

const wrapStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "var(--space-2)",
  padding: "var(--space-6)",
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-sm)",
};

const spinnerColorStyle: CSSProperties = { color: "var(--color-brand-primary)" };

/**
 * Standard inline loading indicator: a spinner plus a short label, announced
 * as a `status` live region. Use it when a query is pending and the page shell
 * is already rendered; pairs with `Page`'s loading slot. Use {@link InlineSpinner}
 * when only the glyph fits.
 */
export function LoadingState({ label }: LoadingStateProps) {
  const strings = useStrings();
  const resolve = useUiText();
  return (
    <div role="status" data-terp="loading-state" style={wrapStyle}>
      <span style={spinnerColorStyle}>
        <InlineSpinner size={20} />
      </span>
      <span>{resolve(label ?? strings.loading)}</span>
    </div>
  );
}

