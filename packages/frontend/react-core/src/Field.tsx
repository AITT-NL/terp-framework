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
  hint?: UiText;
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
 *
 * The error also carries `role="alert"`, and `aria-describedby` is why it has to. A description is
 * read when focus reaches the control, which covers an error that was already there and covers
 * nothing about one that appears on submit — by then focus has left the field, or the button, and
 * the only thing that changed is a span nobody is pointed at. The two are not redundant: they
 * announce at different moments, and a submit-time rejection only has the second one. Because the
 * span is conditional, it enters the accessibility tree exactly when the error appears, which is
 * the event `alert` exists to report.
 */
export function Field({ label, children, error, hint }: FieldProps) {
  const resolve = useUiText();
  const baseId = useId();
  const hasError = error !== undefined && error !== null;
  const hintId = hint !== undefined ? `${baseId}-hint` : undefined;
  const errorId = hasError ? `${baseId}-error` : undefined;
  const described = [hintId, errorId].filter((id) => id !== undefined).join(" ");
  const labelId = `${baseId}-label`;

  // Only a single element child can be named and described — which is the documented contract
  // ("the control"). Anything else is passed through untouched rather than guessed at.
  const control = isValidElement<{
    "aria-describedby"?: string;
    "aria-invalid"?: boolean | "true" | "false";
    "aria-label"?: string;
    "aria-labelledby"?: string;
  }>(children)
    ? cloneElement(children, {
        // The control is named by the label TEXT, not by the label element's subtree, and that
        // distinction is the whole reason this exists. A wrapping label takes its name from
        // everything inside it, so a control that renders an adornment of its own — the password
        // reveal is the first — hands its own button's name to the field: Chromium computes
        // "Password Show password" for that input, which is a WCAG 2.5.3 failure and a sentence
        // no voice-control user can see to say. Pointing at the span makes the name exact.
        //
        // A caller that named the control itself keeps their name; this never overrides one.
        "aria-labelledby":
          children.props["aria-label"] === undefined
            ? (children.props["aria-labelledby"] ?? labelId)
            : undefined,
        "aria-describedby":
          described.length > 0
            ? [children.props["aria-describedby"], described]
                .filter((id) => id !== undefined && id !== "")
                .join(" ")
            : children.props["aria-describedby"],
        "aria-invalid": children.props["aria-invalid"] ?? (hasError ? true : undefined),
      })
    : children;

  return (
    <div data-terp="field">
      <label data-terp="field-label">
        <span id={labelId} data-terp="field-label-text">
          {resolve(label)}
        </span>
        {control}
      </label>
      {hint !== undefined && (
        <span id={hintId} data-terp="field-hint">
          {resolve(hint)}
        </span>
      )}
      {hasError && (
        <span id={errorId} role="alert" data-terp="field-error">
          {error}
        </span>
      )}
    </div>
  );
}
