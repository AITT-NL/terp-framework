import type { CSSProperties, TextareaHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

const textareaStyle: CSSProperties = {
  font: "inherit",
  lineHeight: 1.4,
  padding: "var(--space-2) var(--space-3)",
  border: "1px solid var(--color-neutral-300)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-900)",
  background: "var(--color-neutral-0)",
  boxSizing: "border-box",
};

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Token-styled multiline input — use instead of a raw `<textarea>` (the module-boundary rule).
 */
export function Textarea({ style, ...rest }: TextareaProps) {
  return <textarea data-terp="input" {...rest} style={{ ...textareaStyle, ...style }} />;
}

