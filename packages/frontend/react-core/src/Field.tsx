import { cloneElement, isValidElement, useId } from "react";
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
 *
 * The label needs no wiring because the control sits inside it, but the hint and the error do: text
 * beside a control is invisible to a screen reader unless something points at it. So the field
 * gives each one an id and hands the control an `aria-describedby` — and, when there is an error, an
 * `aria-invalid` that also opts the control into the sheet's invalid border. A control that already
 * declares either keeps its own value; the field adds to `aria-describedby` rather than replacing
 * it. `Input`, `Select`, `Textarea` and `Combobox` all spread their props onto the DOM element, so
 * the attributes land where assistive tech reads them.
 */
export function Field({ label, children, error, hint }: FieldProps) {
  const resolve = useUiText();
  const baseId = useId();
  const hasError = error !== undefined && error !== null;
  const hintId = hint !== undefined ? `${baseId}-hint` : undefined;
  const errorId = hasError ? `${baseId}-error` : undefined;
  const described = [hintId, errorId].filter((id) => id !== undefined).join(" ");

  // Only a single element child can be described — which is the documented contract ("the
  // control"). Anything else is passed through untouched rather than guessed at.
  const control = described.length > 0 && isValidElement<{
    "aria-describedby"?: string;
    "aria-invalid"?: boolean | "true" | "false";
  }>(children)
    ? cloneElement(children, {
        "aria-describedby": [children.props["aria-describedby"], described]
          .filter((id) => id !== undefined && id !== "")
          .join(" "),
        "aria-invalid": children.props["aria-invalid"] ?? (hasError ? true : undefined),
      })
    : children;

  return (
    <div data-terp="field">
      <label data-terp="field-label">
        <span data-terp="field-label-text">{resolve(label)}</span>
        {control}
      </label>
      {hint !== undefined && (
        <span id={hintId} data-terp="field-hint">
          {hint}
        </span>
      )}
      {hasError && (
        <span id={errorId} data-terp="field-error">
          {error}
        </span>
      )}
    </div>
  );
}
