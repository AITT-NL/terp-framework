import type { ChangeEvent, InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { mergeDescribedBy, useControlMessages } from "./controlMessages";

injectTerpStyles();

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "defaultChecked" | "onChange"> {
  label: UiText;
  /** Optional helper text under the control (pointed at by `aria-describedby`). */
  hint?: UiText;
  /** A control-level error, shown under the control and announced when it appears. */
  error?: string | null;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
}

/**
 * Token-styled labelled checkbox — use instead of a raw `<input type="checkbox">`.
 *
 * It carries its own `hint` / `error` rather than going inside a `Field`, because it cannot
 * go inside one: the checkbox renders its own `<label>` around the input, and a `<label>`
 * within `Field`'s `<label>` is invalid HTML — the browser associates the control with the
 * outer one and the field's label text is lost. The wiring is shared with `Field` through
 * `useControlMessages`, so the ids, `aria-describedby`, `aria-invalid` and the error's
 * `role="alert"` behave identically here.
 */
export function Checkbox({
  label,
  hint,
  error,
  checked,
  defaultChecked,
  onChange,
  style,
  ...rest
}: CheckboxProps) {
  const resolve = useUiText();
  const { hasError, describedBy, messages } = useControlMessages(hint, error);
  return (
    // The wrapper is unconditional, and that is not cosmetic. Rendering it only when there is
    // a message would change the element type at this position the moment an error arrives,
    // so React would unmount the label and mount a fresh input — an uncontrolled checkbox
    // would silently lose its state exactly when the form told the user something was wrong.
    <div data-terp="control-field" style={style}>
      <label data-terp="control-label">
        <input
          {...rest}
          type="checkbox"
          data-terp="checkbox"
          checked={checked}
          defaultChecked={defaultChecked}
          // A caller who pointed the control at their own description keeps it: the field's
          // ids are added to theirs, never substituted for them.
          aria-describedby={mergeDescribedBy(rest["aria-describedby"], describedBy)}
          aria-invalid={rest["aria-invalid"] ?? (hasError ? true : undefined)}
          // Attached only when there is something to call, exactly as Select does and for the
          // reason stated there: an unconditional handler silences React's own "you provided a
          // `checked` prop to a form field without an `onChange` handler" guard, so a caller who
          // pinned `checked` and forgot the handler gets a control that looks operable, never
          // changes, and says nothing about it. The spread form is what keeps the prop absent
          // rather than present-and-undefined, which React treats as the same mistake.
          {...(onChange !== undefined
            ? { onChange: (event: ChangeEvent<HTMLInputElement>) => onChange(event.currentTarget.checked) }
            : {})}
        />
        <span>{resolve(label)}</span>
      </label>
      {messages}
    </div>
  );
}
