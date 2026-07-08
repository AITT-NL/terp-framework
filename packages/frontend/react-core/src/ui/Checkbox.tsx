import type { CSSProperties, InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

const labelStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--space-2)",
  color: "var(--color-neutral-900)",
  cursor: "pointer",
  fontSize: "var(--font-size-sm)",
};

const inputStyle: CSSProperties = {
  inlineSize: "1rem",
  blockSize: "1rem",
  accentColor: "var(--color-brand-primary)",
  cursor: "pointer",
};

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
    <label style={{ ...labelStyle, ...style }}>
      <input
        {...rest}
        type="checkbox"
        data-terp="checkbox"
        checked={checked}
        defaultChecked={defaultChecked}
        onChange={(event) => onChange?.(event.currentTarget.checked)}
        style={inputStyle}
      />
      <span>{resolve(label)}</span>
    </label>
  );
}

