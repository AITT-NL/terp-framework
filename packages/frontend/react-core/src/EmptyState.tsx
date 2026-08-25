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
  /**
   * `"compact"` for an empty block that is not the whole screen.
   *
   * The default is sized to be the only thing on a page — generous padding, a 2rem
   * glyph, centred. That is right for an empty list and wrong the moment a screen has two
   * of them: stacked, they were 480px of chrome repeating a sentence, and the emptiness of
   * one section is not the page's headline. Compact keeps the frame and the wording and
   * takes back the space — tighter padding, a smaller glyph, left-aligned, because a
   * block that is one item among several reads as a row rather than a poster.
   */
  size?: "default" | "compact";
}

/**
 * The standard "nothing here yet" block: use whenever a query legitimately returns zero
 * rows, a module is not wired to data yet, or a feature is gated. One recognisable empty
 * UX platform-wide tells the user "this is not an error — there is just nothing to show",
 * and the `action` slot turns the dead end into the obvious next step.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  size = "default",
}: EmptyStateProps) {
  const resolve = useUiText();
  const compact = size === "compact";
  const leading = icon ?? (
    <span data-terp="empty-state-icon">
      <Icon name="inbox" size={compact ? "1.25rem" : "2rem"} />
    </span>
  );
  // Stamped only for `compact`: the full-page block's geometry IS the base rule, the same
  // shape `Button`'s sizes and the shell's density take.
  return (
    <div data-terp="empty-state" data-size={compact ? "compact" : undefined}>
      {leading}
      <p data-terp="empty-state-title">{resolve(title)}</p>
      {description !== undefined && <div data-terp="empty-state-description">{description}</div>}
      {action}
    </div>
  );
}

