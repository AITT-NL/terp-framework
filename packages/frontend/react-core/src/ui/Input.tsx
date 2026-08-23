import { useState } from "react";
import type { InputHTMLAttributes } from "react";

import { Icon } from "../icons";
import { injectTerpStyles } from "../styles";
import { useStrings } from "../uiText";

injectTerpStyles();

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/**
 * Token-styled text input — use instead of a raw `<input>` (the module-boundary rule).
 * The `data-terp="input"` marker is the whole styling hook: it carries the shared control
 * surface, the focus ring, the hover border and the disabled treatment from the injected
 * sheet, with the element type deciding the geometry (ADR 0094).
 *
 * `type="password"` additionally grows a reveal toggle, and it is the TYPE that decides rather
 * than a prop, for the reason the sheet already gives about `input` and `textarea`: "only their
 * geometry differs, so the element type carries that — no second attribute for a distinction the
 * tag name already makes." A `PasswordInput` export would be the `LoadingButton` mistake, a second
 * name for one `<input>`.
 *
 * An app cannot build this itself, which is why it belongs here rather than in a recipe. The toggle
 * needs a positioned wrapper, and `BOUNDARY_SPEC` refuses both `style` and `className` in module
 * files — exactly the `Button.fullWidth` case: a shape the framework can produce and its consumers
 * cannot ask for.
 */
export function Input({ type, ...rest }: InputProps) {
  const strings = useStrings();
  const [revealed, setRevealed] = useState(false);

  if (type !== "password") {
    return <input data-terp="input" type={type} {...rest} />;
  }

  // A field the caller has switched off is switched off as a whole. Without this the value stays
  // hidden and unreachable while the control beside it still reveals it — a disabled field with a
  // working button in it.
  const inert = rest.disabled === true || rest.readOnly === true;

  return (
    <span data-terp="input-password">
      {/*
        `rest` spreads onto the INPUT, never onto the wrapper, and that is load-bearing rather than
        tidy. `Field` clones its control to inject `aria-describedby` and `aria-invalid`, and the
        sheet's invalid border is `input[data-terp="input"][aria-invalid="true"]` — a single-element
        selector. Land those on the span and the attribute matches nothing while the marker sits on
        a different element, so the red border silently disappears for every password field with a
        hint or an error. There is one live today.
      */}
      <input
        data-terp="input"
        type={revealed ? "text" : "password"}
        // Revealing swaps the type to `text`, and a text input is a candidate for spellcheck,
        // autocorrect and autocapitalisation in engines that apply them — none of which a password
        // wants, and two of which would silently rewrite what the user typed on a phone. Declared
        // before the spread so a caller can still override them.
        spellCheck={false}
        autoCorrect="off"
        autoCapitalize="none"
        {...rest}
      />
      <button
        type="button"
        data-terp="iconbutton"
        disabled={inert}
        // No `aria-pressed`. The name already carries the state — it swaps between "Show password"
        // and "Hide password" — and encoding it twice makes the two disagree: a toggle announced
        // as "Hide password, pressed" claims the value is hidden and shown at once. It also keeps
        // this button out of the shared hover guard, which excludes `[aria-pressed="true"]` and
        // would otherwise leave the revealed toggle with no hover feedback at all.
        aria-label={revealed ? strings.hidePassword : strings.showPassword}
        onClick={() => setRevealed((on) => !on)}
      >
        <Icon name={revealed ? "eye-off" : "eye"} />
      </button>
    </span>
  );
}
