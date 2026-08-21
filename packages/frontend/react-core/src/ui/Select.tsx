import type { ChangeEvent, ReactNode, SelectHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

/**
 * One choice in a {@link Select}'s `options` list.
 *
 * `value` is the type parameter rather than `string`, which is the whole point of the list
 * existing: a closed enum passed here checks its own members, so a typo is a typecheck error
 * instead of an option nobody can select. `ComboboxOption` is the same shape without the
 * parameter, and it can follow the day something asks — widening it is additive.
 */
export interface SelectOption<T extends string = string> {
  value: T;
  /** Display text; a {@link UiText} descriptor so a translated label is expressible. */
  label: UiText;
  disabled?: boolean;
}

type SelectBase = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "value" | "defaultValue" | "onChange" | "children"
>;

type SelectValueProps<T extends string> = {
  value?: T;
  defaultValue?: T;
  /** The raw DOM event, unchanged — for a caller that needs the element or the event. */
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  /**
   * The selected value, typed.
   *
   * This is the half that removes the cast. `event.target.value` is `string` whatever the
   * options say, so a closed enum used with `onChange` alone needs
   * `setStatus(event.target.value as Status)` at every call site — and the cast is exactly
   * where a wrong value gets in. With `options` given, `T` is inferred from them.
   */
  onValueChange?: (value: T) => void;
};

/**
 * Props, as a union of the two ways to give a `<select>` its choices.
 *
 * A union rather than two optional props, and that is deliberate: rendering `options` while
 * silently ignoring `children` would be a prop that works in one branch and does nothing in
 * the other, which is the defect shape the 4a/4b review found twice in one release. Here the
 * combination does not typecheck, so there is no silent branch to be in.
 */
export type SelectProps<T extends string = string> = SelectBase &
  SelectValueProps<T> &
  (
    | {
        /** The choices, as data. Mutually exclusive with `children`. */
        options: readonly SelectOption<T>[];
        /**
         * A leading, disabled, empty-valued row — the "choose one" case.
         *
         * `placeholder` is not an attribute a `<select>` has, so this renders the
         * `<option value="" disabled>` that every app was writing by hand. It is only
         * offered on the `options` branch: with raw children the caller writes it directly.
         */
        placeholder?: UiText;
        children?: never;
      }
    | { options?: never; placeholder?: never; children: ReactNode }
  );

/**
 * Token-styled select — use instead of a raw `<select>` (the module-boundary rule).
 *
 * Two forms. Pass `options` (with `onValueChange` for a typed callback) when the choices are
 * data, which is the common case and the one that had no support: a closed enum needed a
 * hand-written `<option>` per member plus a cast on the way out, so every app grew its own
 * `EnumSelect<T>` wrapper. Or pass `<option>` children as before, unchanged.
 *
 * The `data-terp="input"` marker opts the element into the shared control surface and focus
 * ring; the sheet replaces the native affordance with an SVG chevron so the control looks the
 * same on every platform (ADR 0094). Neither form renders an inline style.
 */
export function Select<T extends string = string>({
  onChange,
  onValueChange,
  ...props
}: SelectProps<T>) {
  const resolve = useUiText();
  // Destructured off `props` rather than in the signature: the two branches of the union do
  // not both declare them, so naming them there would widen the parameter type to the
  // intersection and lose the exclusivity the union exists to enforce.
  const { options, placeholder, children, ...rest } = props as SelectBase & {
    options?: readonly SelectOption<T>[];
    placeholder?: UiText;
    children?: ReactNode;
  };
  return (
    <select
      data-terp="input"
      {...rest}
      onChange={(event) => {
        onChange?.(event);
        onValueChange?.(event.target.value as T);
      }}
    >
      {options === undefined ? (
        children
      ) : (
        <>
          {placeholder !== undefined && (
            <option value="" disabled>
              {resolve(placeholder)}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {resolve(option.label)}
            </option>
          ))}
        </>
      )}
    </select>
  );
}
