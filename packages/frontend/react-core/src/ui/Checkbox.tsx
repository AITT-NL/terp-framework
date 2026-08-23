import type { ChangeEvent, InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "defaultChecked" | "onChange"> {
  label: UiText;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
}

/** Token-styled labelled checkbox — use instead of a raw `<input type="checkbox">`. */
export function Checkbox({ label, checked, defaultChecked, onChange, style, ...rest }: CheckboxProps) {
  const resolve = useUiText();
  return (
    <label data-terp="control-label" style={style}>
      <input
        {...rest}
        type="checkbox"
        data-terp="checkbox"
        checked={checked}
        defaultChecked={defaultChecked}
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
  );
}

