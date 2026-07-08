import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Optional leading icon, rendered before `children` (e.g. `<Icon name="plus" />`). */
  icon?: ReactNode;
}

const baseStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "var(--space-2)",
  font: "inherit",
  fontWeight: "var(--font-weight-medium)" as never,
  lineHeight: 1,
  minHeight: "2.25rem",
  padding: "0 var(--space-4)",
  border: "1px solid transparent",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const variantStyle: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: "var(--color-brand-primary)",
    color: "var(--color-brand-primary-contrast)",
    boxShadow: "var(--shadow-sm)",
  },
  secondary: {
    background: "var(--color-neutral-0)",
    color: "var(--color-neutral-900)",
    borderColor: "var(--color-neutral-300)",
  },
  danger: {
    background: "var(--color-status-danger)",
    color: "var(--color-neutral-0)",
  },
  ghost: {
    background: "transparent",
    color: "var(--color-neutral-700)",
  },
};

const iconWrapStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  flexShrink: 0,
};

/**
 * Token-styled button — use instead of a raw `<button>` (the module-boundary rule). It
 * styles only via the design-token CSS variables, so it themes with the app. Hover,
 * active and `:focus-visible` states are layered on via the injected react-core sheet,
 * keyed by the `data-terp` / `data-variant` attributes set below.
 */
export function Button({
  variant = "primary",
  icon,
  style,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      data-terp="button"
      data-variant={variant}
      {...rest}
      style={{ ...baseStyle, ...variantStyle[variant], ...style }}
    >
      {icon !== undefined && (
        <span aria-hidden="true" style={iconWrapStyle}>
          {icon}
        </span>
      )}
      {children}
    </button>
  );
}

