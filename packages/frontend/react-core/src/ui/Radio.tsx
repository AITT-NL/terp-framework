import { useId, useState } from "react";
import type { ChangeEvent, InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

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
    <label data-terp="control-label" style={style}>
      <input
        {...rest}
        type="radio"
        data-terp="radio"
        value={value}
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

export interface RadioOption {
  value: string;
  label: UiText;
  disabled?: boolean;
}

export interface RadioGroupProps {
  label: UiText;
  name?: string;
  options?: readonly RadioOption[];
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
    <fieldset data-terp="radio-group">
      <legend data-terp="radio-group-legend">{resolve(label)}</legend>
      <div data-terp="radio-group-options">
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
      </div>
    </fieldset>
  );
}
