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

/** Everything a raw `<select>` accepts, minus what the two forms disagree about. */
type SelectBase = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "children" | "value" | "defaultValue"
>;

/** The unselected state a `placeholder` occupies — an empty value, as HTML spells it. */
type Unselected = "";

/**
 * Props: the shared surface, plus a union over the two ways to give a `<select>` its choices.
 *
 * Four things here were each arrived at by breaking the alternative and measuring it, so they
 * are worth stating rather than rediscovering.
 *
 * **`onValueChange` sits outside the union, and its parameter is `NoInfer`.** Inside the union
 * the prop has two signatures and TypeScript cannot contextually type a parameter across a
 * union of signatures: `onValueChange={(value) => …}` came back as an implicit `any`, which
 * under `noImplicitAny` is an error the caller must paper over with an annotation — very nearly
 * the cast this prop exists to remove. Outside the union it infers, but then the *callback*
 * becomes an inference site for `T`: with raw children,
 * `<Select onValueChange={setStatus}><option value="dong"/></Select>` took `T` from `setStatus`
 * and never compared the children to it, so the one thing the prop promises to prevent was
 * exactly what it allowed. `NoInfer` leaves the options list as the only inference site.
 *
 * **The value narrowing is on the options branch only.** Narrowing `value` to `T` is what
 * removes `as Status`, but `T` can only come from an options list — so on the raw-children
 * branch the same narrowing buys nothing and costs two shapes a `<select>` genuinely has:
 * `multiple` with a `readonly string[]` value, and a numeric `value`.
 *
 * **A placeholder widens the value to `""`.** HTML's own selectedness algorithm picks the first
 * option that is *not disabled*, so a disabled placeholder row is skipped and the control opens
 * on the first real choice — measured: `value=open, selectedIndex=1`. Showing the placeholder
 * means the select's value is the empty string, which is therefore part of the type rather than
 * something a caller has to cast to.
 *
 * **The two forms are a union.** Rendering `options` while silently ignoring `children` would be
 * a prop that works in one branch and does nothing in the other. `children` stays optional,
 * though: a `<Select>` with no choices yet was legal before this component took an options list
 * and still is.
 */
export type SelectProps<T extends string = string> = SelectBase & {
  /**
   * The selected value, typed.
   *
   * With `options` given, `T` is inferred from them, so the callback is checked against the
   * choices. With raw children there is nothing to infer from and `T` stays `string` — which
   * is deliberate: nothing checks hand-written `<option>` values, so a narrower promise here
   * would be a false one.
   */
  onValueChange?: (value: NoInfer<T>) => void;
} & (
    | {
        /** The choices, as data. Mutually exclusive with `children`. */
        options: readonly SelectOption<T>[];
        /**
         * A leading, disabled, empty-valued row — the "choose one" case.
         *
         * `placeholder` is not an attribute a `<select>` honours, so this renders the
         * `<option value="" disabled>` every app was writing by hand, AND selects it when the
         * caller has pinned no value of their own. Both halves are needed: without the second
         * the row exists and is never shown.
         */
        placeholder?: UiText;
        /**
         * `NoInfer` is load-bearing. Without it `value` is a second inference site for `T`, so
         * `value="dong"` beside a `SelectOption<Status>[]` list widens the parameter to
         * `Status | "dong"` and compiles — the value checked against a type it helped choose.
         */
        value?: NoInfer<T> | Unselected;
        defaultValue?: NoInfer<T> | Unselected;
        children?: never;
      }
    | {
        options?: never;
        value?: SelectHTMLAttributes<HTMLSelectElement>["value"];
        defaultValue?: SelectHTMLAttributes<HTMLSelectElement>["defaultValue"];
        children?: ReactNode;
      }
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
export function Select<T extends string = string>(props: SelectProps<T>) {
  const resolve = useUiText();
  // Destructured from a cast rather than in the signature: the branches of the union do not
  // both declare these keys, so naming them as parameters would widen the parameter type to
  // the intersection and lose the exclusivity the union exists to enforce.
  const {
    options,
    placeholder,
    children,
    onChange,
    onValueChange,
    value,
    defaultValue,
    ...rest
  } = props as SelectBase & {
    options?: readonly SelectOption<T>[];
    placeholder?: UiText;
    children?: ReactNode;
    onValueChange?: (value: string) => void;
    value?: string | number | readonly string[];
    defaultValue?: string | number | readonly string[];
  };

  // A placeholder the browser never selects is the row existing without the feature working,
  // so an unpinned select with one starts empty. Only when the caller pinned neither, and only
  // as `defaultValue` — passing both is a React warning, and pinning `value` would make every
  // placeholder select controlled.
  const startsUnselected =
    placeholder !== undefined && value === undefined && defaultValue === undefined;

  // Attached only when there is something to call. An unconditional handler silences React's
  // own "you provided a `value` prop to a form field without an `onChange` handler" guard, so a
  // caller who forgot the handler would get a control that looks editable, never updates, and
  // says nothing about it.
  const handlesChange = onChange !== undefined || onValueChange !== undefined;

  return (
    <select
      data-terp="input"
      {...rest}
      value={value}
      defaultValue={startsUnselected ? "" : defaultValue}
      onChange={
        handlesChange
          ? (event: ChangeEvent<HTMLSelectElement>) => {
              onChange?.(event);
              onValueChange?.(event.target.value);
            }
          : undefined
      }
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
