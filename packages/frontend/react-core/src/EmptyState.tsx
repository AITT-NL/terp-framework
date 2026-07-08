import type { CSSProperties, ReactNode } from "react";

import { Icon } from "./icons";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

export interface EmptyStateProps {
  /**
   * Optional leading visual (any rendered node — react-core takes no icon dependency).
   * Defaults to a muted inbox glyph so the block always has a recognisable frame.
   */
  icon?: ReactNode;
  /** Short title — what is missing. */
  title: UiText;
  /** Optional explanation — why it's missing, or what to do next. */
  description?: ReactNode;
  /** Optional call to action (typically a `Button`). */
  action?: ReactNode;
}

const wrapStyle: CSSProperties = {
  display: "grid",
  justifyItems: "center",
  gap: "var(--space-3)",
  padding: "var(--space-8) var(--space-6)",
  textAlign: "center",
  color: "var(--color-neutral-600)",
  border: "1px dashed var(--color-neutral-300)",
  borderRadius: "var(--radius-lg)",
  background: "var(--color-neutral-0)",
};

const iconStyle: CSSProperties = {
  color: "var(--color-neutral-400)",
  display: "inline-flex",
};

const titleStyle: CSSProperties = {
  margin: 0,
  color: "var(--color-neutral-900)",
  fontSize: "var(--font-size-base)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
};

const descriptionStyle: CSSProperties = {
  color: "var(--color-neutral-600)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
  maxWidth: "36ch",
};

/**
 * The standard "nothing here yet" block: use whenever a query legitimately returns zero
 * rows, a module is not wired to data yet, or a feature is gated. One recognisable empty
 * UX platform-wide tells the user "this is not an error — there is just nothing to show",
 * and the `action` slot turns the dead end into the obvious next step.
 */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  const resolve = useUiText();
  const leading = icon ?? (
    <span style={iconStyle}>
      <Icon name="inbox" size="2rem" />
    </span>
  );
  return (
    <div data-terp="empty-state" style={wrapStyle}>
      {leading}
      <p style={titleStyle}>{resolve(title)}</p>
      {description !== undefined && <div style={descriptionStyle}>{description}</div>}
      {action}
    </div>
  );
}

