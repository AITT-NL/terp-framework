import type { ReactNode } from "react";

import { Icon } from "./icons";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

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

/**
 * The standard "nothing here yet" block: use whenever a query legitimately returns zero
 * rows, a module is not wired to data yet, or a feature is gated. One recognisable empty
 * UX platform-wide tells the user "this is not an error — there is just nothing to show",
 * and the `action` slot turns the dead end into the obvious next step.
 */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  const resolve = useUiText();
  const leading = icon ?? (
    <span data-terp="empty-state-icon">
      <Icon name="inbox" size="2rem" />
    </span>
  );
  return (
    <div data-terp="empty-state">
      {leading}
      <p data-terp="empty-state-title">{resolve(title)}</p>
      {description !== undefined && <div data-terp="empty-state-description">{description}</div>}
      {action}
    </div>
  );
}

