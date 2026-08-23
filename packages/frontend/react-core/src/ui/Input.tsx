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
      <input data-terp="input" type={revealed ? "text" : "password"} {...rest} />
      <button
        type="button"
        data-terp="iconbutton"
        // `aria-pressed` rather than two buttons: it is one control whose state changes, and a
        // screen reader announces the state without the name having to encode it.
        aria-pressed={revealed}
        aria-label={revealed ? strings.hidePassword : strings.showPassword}
        onClick={() => setRevealed((on) => !on)}
      >
        <Icon name={revealed ? "eye-off" : "eye"} />
      </button>
    </span>
  );
}
