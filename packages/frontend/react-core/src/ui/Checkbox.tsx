import type { InputHTMLAttributes } from "react";

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
        onChange={(event) => onChange?.(event.currentTarget.checked)}
      />
      <span>{resolve(label)}</span>
    </label>
  );
}

