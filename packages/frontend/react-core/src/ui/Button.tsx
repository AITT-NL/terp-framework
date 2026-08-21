import type { ButtonHTMLAttributes, ReactNode } from "react";

import { InlineSpinner } from "../LoadingState";
import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

/** Control size: `"md"` is the standard control and needs no attribute (see below). */
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /**
   * Control size (default `"md"`). Changes the height, the horizontal padding and the label
   * size together; composes with `data-density`, so a `"sm"` button inside a compact subtree
   * is shorter still.
   */
  size?: ButtonSize;
  /**
   * The action is in flight: shows a spinner in the icon slot, marks the control
   * `aria-busy` and disables it, so a second click cannot start the request twice.
   *
   * The spinner replaces `icon` rather than joining it, which keeps the button's width from
   * jumping as it enters and leaves the state.
   */
  loading?: boolean;
  /**
   * Fill the container's inline size instead of the label's.
   *
   * It exists because the alternative was `style={{ width: "100%" }}`, which app modules may
   * not write (ADR 0059) — so full width was a shape the framework could produce and its
   * consumers could not ask for.
   */
  fullWidth?: boolean;
  /** Optional leading icon, rendered before `children` (e.g. `<Icon name="plus" />`). */
  icon?: ReactNode;
}

/**
 * Token-styled button — use instead of a raw `<button>` (the module-boundary rule).
 *
 * It renders no inline styles: the geometry, the per-variant colours and the hover /
 * active / disabled / `:focus-visible` states all live in the injected react-core sheet,
 * matched on the `data-terp` / `data-variant` attributes set below (ADR 0094). So the
 * variant is a fact about the element rather than a style object chosen in here — which
 * is what a test should assert, and what an app's `theme.css` can restyle.
 *
 * `size`, `loading` and `fullWidth` are all closed sets, so all three are attributes with a
 * rule each (ADR 0094 §3). Two details about how they are stamped are deliberate:
 *
 * `data-size` appears only for `"sm"` and `"lg"`. The standard control's geometry IS the base
 * rule, so `md` is the absence of an attribute — the same shape density takes, where
 * "comfortable" is the token sheet's `:root` value and the attribute for it matches no rule.
 * (`data-variant` is stamped even for its default because `primary` has a rule of its own;
 * the two idioms differ for that reason rather than by accident.)
 *
 * `loading` sets `disabled` as well, and the sizes are expressed as a `calc()` off the
 * density token rather than as heights of their own, so density keeps composing with all
 * three sizes without a second family of tokens to keep in step.
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  fullWidth = false,
  icon,
  type = "button",
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const leading = loading ? <InlineSpinner size={14} /> : icon;
  return (
    <button
      type={type}
      data-terp="button"
      data-variant={variant}
      data-size={size === "md" ? undefined : size}
      data-loading={loading ? "true" : undefined}
      data-full-width={fullWidth ? "true" : undefined}
      disabled={disabled === true || loading}
      aria-busy={loading ? true : undefined}
      {...rest}
    >
      {leading !== undefined && leading !== null && (
        <span aria-hidden="true" data-terp="button-icon">
          {leading}
        </span>
      )}
      {children}
    </button>
  );
}
