import type { ReactNode } from "react";

import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

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
    <div data-terp="field">
      <label data-terp="field-label">
        <span data-terp="field-label-text">{resolve(label)}</span>
        {children}
      </label>
      {hint !== undefined && <span data-terp="field-hint">{hint}</span>}
      {error !== undefined && error !== null && <span data-terp="field-error">{error}</span>}
    </div>
  );
}
