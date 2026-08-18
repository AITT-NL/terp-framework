import type { SelectHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

/**
 * Token-styled select — use instead of a raw `<select>` (the module-boundary rule). Pass
 * `<option>` children as usual. The `data-terp="input"` marker opts the element into the
 * shared control surface and focus ring; the sheet replaces the native affordance with an
 * SVG chevron so the control looks the same on every platform (ADR 0094).
 */
export function Select(props: SelectProps) {
  return <select data-terp="input" {...props} />;
}
