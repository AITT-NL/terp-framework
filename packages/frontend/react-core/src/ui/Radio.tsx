import { useId, useState } from "react";
import type { CSSProperties, InputHTMLAttributes, ReactNode } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

const groupStyle: CSSProperties = { display: "grid", gap: "var(--space-2)", border: 0, padding: 0, margin: 0 };
const legendStyle: CSSProperties = {
  fontWeight: "var(--font-weight-medium)" as never,
  padding: 0,
  marginBlockEnd: "var(--space-1)",
  fontSize: "var(--font-size-sm)",
  color: "var(--color-neutral-700)",
};
const optionsStyle: CSSProperties = { display: "grid", gap: "var(--space-2)" };
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

export interface RadioProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "defaultChecked" | "onChange" | "value"> {
  label: UiText;
  value: string;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
}

/** Token-styled labelled radio — usually rendered by {@link RadioGroup}. */
export function Radio({ label, value, checked, defaultChecked, onChange, style, ...rest }: RadioProps) {
  const resolve = useUiText();
  return (
    <label style={{ ...labelStyle, ...style }}>
      <input
        {...rest}
        type="radio"
        data-terp="radio"
        value={value}
        checked={checked}
        defaultChecked={defaultChecked}
        onChange={(event) => onChange?.(event.currentTarget.checked)}
        style={inputStyle}
      />
      <span>{resolve(label)}</span>
    </label>
  );
}

export interface RadioOption {
  value: string;
  label: UiText;
  disabled?: boolean;
}

export interface RadioGroupProps {
  label: UiText;
  name?: string;
  options?: readonly RadioOption[];
  children?: ReactNode;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
}

/** Accessible token-styled radio group; pass `options` for the standard generated radios. */
export function RadioGroup({
  label,
  name,
  options,
  children,
  value,
  defaultValue,
  onChange,
  disabled = false,
}: RadioGroupProps) {
  const generatedName = useId();
  const resolve = useUiText();
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue ?? "");
  const selected = value ?? uncontrolledValue;
  const groupName = name ?? generatedName;

  function select(next: string) {
    if (value === undefined) {
      setUncontrolledValue(next);
    }
    onChange?.(next);
  }

  return (
    <fieldset style={groupStyle}>
      <legend style={legendStyle}>{resolve(label)}</legend>
      <div style={optionsStyle}>
        {options?.map((option) => (
          <Radio
            key={option.value}
            name={groupName}
            value={option.value}
            label={option.label}
            checked={selected === option.value}
            disabled={disabled || option.disabled}
            onChange={(checked) => {
              if (checked) {
                select(option.value);
              }
            }}
          />
        ))}
        {children}
      </div>
    </fieldset>
  );
}
