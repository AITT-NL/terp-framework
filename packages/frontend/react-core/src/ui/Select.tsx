import type { CSSProperties, SelectHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { CONTROL_TEXT_STYLE } from "./controlStyles";

injectTerpStyles();

// SVG chevron rendered via a data URL background — keeps the token-only styling
// contract while giving <select> a consistent affordance across platforms.
const chevronUrl =
  "url(\"data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none' stroke='%2364748b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m5 8 5 5 5-5'/%3E%3C/svg%3E\")";

const selectStyle: CSSProperties = {
  ...CONTROL_TEXT_STYLE,
  lineHeight: 1.2,
  maxWidth: "100%",
  minWidth: 0,
  minHeight: "2.25rem",
  padding: "0 calc(var(--space-3) + 1.25rem) 0 var(--space-3)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-900)",
  background: `${chevronUrl} no-repeat right var(--space-2) center / 1rem 1rem, var(--color-neutral-0)`,
  boxSizing: "border-box",
  appearance: "none",
  WebkitAppearance: "none",
  MozAppearance: "none",
};

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

/**
 * Token-styled select — use instead of a raw `<select>` (the module-boundary rule). Pass `<option>`
 * children as usual. The `data-terp="input"` marker opts the element into the shared focus
 * ring; a subtle SVG chevron replaces the native affordance for a consistent look.
 */
export function Select({ style, ...rest }: SelectProps) {
  return <select data-terp="input" {...rest} style={{ ...selectStyle, ...style }} />;
}

