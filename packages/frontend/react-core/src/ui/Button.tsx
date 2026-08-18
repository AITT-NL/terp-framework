import type { ButtonHTMLAttributes, ReactNode } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
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
 */
export function Button({
  variant = "primary",
  icon,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button type={type} data-terp="button" data-variant={variant} {...rest}>
      {icon !== undefined && (
        <span aria-hidden="true" data-terp="button-icon">
          {icon}
        </span>
      )}
      {children}
    </button>
  );
}

