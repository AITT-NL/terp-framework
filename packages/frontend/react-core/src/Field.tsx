import type { CSSProperties, ReactNode } from "react";

import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

const fieldStyle: CSSProperties = { display: "grid", gap: "var(--space-1)" };
const labelStyle: CSSProperties = {
  fontWeight: "var(--font-weight-medium)" as never,
  fontSize: "var(--font-size-sm)",
  color: "var(--color-neutral-700)",
};
const hintStyle: CSSProperties = {
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-xs)",
};
const errorStyle: CSSProperties = {
  color: "var(--color-status-danger)",
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-medium)" as never,
};

export interface FieldProps {
  /** The field label (also the control's accessible name — the control is wrapped in the `<label>`). */
  label: UiText;
  /** The control: an `<Input>`, `<Select>`, or `<Textarea>`. */
  children: ReactNode;
  /** A field-level error (e.g. mapped from a 422), shown under the control. */
  error?: string | null;
  /** Optional helper text under the control. */
  hint?: string;
}

/**
 * A labelled form field: wraps a control in a `<label>` (so the label is its accessible name with no
 * id wiring) and renders an optional hint + a field-level error. Compose it with the token-styled
 * `Input` / `Select` / `Textarea` primitives to build a multi-field form — the centralized, accessible
 * way every module authors inputs.
 */
export function Field({ label, children, error, hint }: FieldProps) {
  const resolve = useUiText();
  return (
    <div style={fieldStyle}>
      <label style={fieldStyle}>
        <span style={labelStyle}>{resolve(label)}</span>
        {children}
      </label>
      {hint !== undefined && <span style={hintStyle}>{hint}</span>}
      {error !== undefined && error !== null && <span style={errorStyle}>{error}</span>}
    </div>
  );
}
