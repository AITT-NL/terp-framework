import type { InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/**
 * Token-styled text input — use instead of a raw `<input>` (the module-boundary rule).
 * The `data-terp="input"` marker is the whole styling hook: it carries the shared control
 * surface, the focus ring, the hover border and the disabled treatment from the injected
 * sheet, with the element type deciding the geometry (ADR 0094).
 */
export function Input(props: InputProps) {
  return <input data-terp="input" {...props} />;
}
