import type { CSSProperties, InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { CONTROL_TEXT_STYLE } from "./controlStyles";

injectTerpStyles();

const inputStyle: CSSProperties = {
  ...CONTROL_TEXT_STYLE,
  lineHeight: 1.2,
  minHeight: "2.25rem",
  padding: "0 var(--space-3)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-900)",
  background: "var(--color-neutral-0)",
  boxSizing: "border-box",
};

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/**
 * Token-styled text input — use instead of a raw `<input>` (the module-boundary rule).
 * The `data-terp="input"` marker opts the element into the shared focus ring and
 * hover polish injected by react-core.
 */
export function Input({ style, ...rest }: InputProps) {
  return <input data-terp="input" {...rest} style={{ ...inputStyle, ...style }} />;
}

