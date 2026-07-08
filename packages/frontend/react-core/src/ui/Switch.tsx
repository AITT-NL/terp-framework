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
  inlineSize: "2.25rem",
  blockSize: "1.25rem",
  accentColor: "var(--color-brand-primary)",
  cursor: "pointer",
  transition: "background-color 150ms ease",
};

export interface SwitchProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "defaultChecked" | "onChange" | "role"> {
  label: UiText;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
}

/** Token-styled labelled switch for boolean settings. */
export function Switch({ label, checked, defaultChecked, onChange, style, ...rest }: SwitchProps) {
  const resolve = useUiText();
  return (
    <label style={{ ...labelStyle, ...style }}>
      <input
        {...rest}
        type="checkbox"
        role="switch"
        data-terp="switch"
        checked={checked}
        defaultChecked={defaultChecked}
        onChange={(event) => onChange?.(event.currentTarget.checked)}
        style={inputStyle}
      />
      <span>{resolve(label)}</span>
    </label>
  );
}

