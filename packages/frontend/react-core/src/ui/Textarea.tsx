import type { TextareaHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Token-styled multiline input — use instead of a raw `<textarea>` (the module-boundary
 * rule). Shares the `data-terp="input"` control surface; the sheet gives it the looser
 * line height and block padding multiline copy needs (ADR 0094).
 */
export function Textarea(props: TextareaProps) {
  return <textarea data-terp="input" {...props} />;
}
