import { useId } from "react";
import type { ReactNode } from "react";

import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

/**
 * The hint + error half of a form field, shared by `Field` and the three self-labelling
 * controls (`Switch`, `Checkbox`, `RadioGroup`).
 *
 * It exists because those three cannot use `Field` at all. Each renders its own `<label>`
 * (or, for the group, a `<fieldset>`/`<legend>`) around the input, and `Field` labels its
 * child by wrapping it in a `<label>` — nesting the two produces a `<label>` inside a
 * `<label>`, which HTML forbids and browsers resolve by associating the control with the
 * outer one. So the envelope had to be given to them separately, and the point of sharing
 * this is that "separately" does not become "differently": the ids, the
 * `aria-describedby` composition, the `aria-invalid`, and the error's `role="alert"` are
 * one implementation, not four that drift.
 *
 * On `role="alert"`: `aria-describedby` is read when focus reaches the control, which
 * covers an error that was already there and covers nothing about one that arrives on
 * submit — by then focus has left the field and the only thing that changed is a span
 * nobody is pointed at. The two announce at different moments, and a submit-time
 * rejection only has the second.
 */
export interface ControlMessages {
  /** True when an error is present — the caller puts this on `aria-invalid`. */
  hasError: boolean;
  /** The `aria-describedby` value for the control, or `undefined` when there is nothing to say. */
  describedBy: string | undefined;
  /** The rendered hint and error nodes, placed after the control by the caller. */
  messages: ReactNode;
}

export function useControlMessages(
  hint: UiText | undefined,
  error: string | null | undefined,
): ControlMessages {
  const resolve = useUiText();
  const baseId = useId();
  const hasError = error !== undefined && error !== null;
  const hintId = hint !== undefined ? `${baseId}-hint` : undefined;
  const errorId = hasError ? `${baseId}-error` : undefined;
  const describedBy =
    [hintId, errorId].filter((id) => id !== undefined).join(" ") || undefined;

  return {
    hasError,
    describedBy,
    messages: (
      <>
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
      </>
    ),
  };
}

/**
 * Merge a caller's own `aria-describedby` with the field's, rather than replacing it.
 *
 * A control that already points at something keeps pointing at it: dropping the caller's
 * value would silently remove a description they added deliberately, and an assistive
 * technology would simply stop reading it with no error anywhere.
 */
export function mergeDescribedBy(
  own: string | undefined,
  added: string | undefined,
): string | undefined {
  return (
    [own, added].filter((id) => id !== undefined && id !== "").join(" ") || undefined
  );
}
