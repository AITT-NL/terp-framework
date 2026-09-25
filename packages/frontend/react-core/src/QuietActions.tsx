import type { HTMLAttributes, ReactNode } from "react";

import type { SpaceToken } from "./layout";
import { injectTerpStyles } from "./styles";

injectTerpStyles();

export interface QuietActionsProps extends Omit<HTMLAttributes<HTMLDivElement>, "style"> {
  /**
   * The action, or actions, that stay quiet until someone reaches for them.
   *
   * A slot rather than a convention about which children are actions, and it is the same
   * slot `Card` publishes, for the same reason: "every Button inside" would be a rule a
   * reader has to know before they can predict what a row will do, and it would capture a
   * button that happened to be part of the value.
   */
  actions: ReactNode;
  /** Distance between the value and its actions, as a step on the token spacing scale (default `1`). */
  gap?: SpaceToken;
  /** The value the actions belong to. */
  children: ReactNode;
}

/**
 * A value with an action attached, where the action is quiet until someone reaches for it.
 *
 * The case it was written for is a row of identifiers. A revision card carries five copyable
 * digests, so it also carried five copy buttons, and the affordance was then repeated more
 * often than the values it applied to -- five controls competing with five twelve-character
 * chips that are themselves the thing a reader came to look at. Below the viewport cutover
 * each of those buttons took a line of its own. The same shape turns up wherever a list row
 * owns an action: a remove, an open, a pin.
 *
 * **The space is reserved, not collapsed.** The action fades rather than appearing, so
 * nothing on the row moves when a pointer arrives -- a value that reflows under the cursor is
 * a value you cannot click, and a row of them makes a card twitch as the mouse crosses it.
 *
 * Three things make it safe rather than merely quiet, and each closes a way this pattern is
 * usually got wrong:
 *
 * - **It reveals on focus as well as hover**, through `:focus-within` on the row. Opacity does
 *   not remove an element from the tab order -- which is correct, the action must stay
 *   reachable -- so without this a keyboard user would tab to a control they cannot see.
 * - **It only hides where hovering is possible at all.** On a touch screen there is no hover
 *   to reveal anything, so the action would be permanently invisible and permanently
 *   tappable. The rule sits behind `@media (hover: hover)` and a touch device simply gets a
 *   visible action.
 * - **It is invisible to the accessibility tree either way.** Opacity is not `visibility`, so
 *   the action is announced, named and operable at every moment; what changes is only whether
 *   a sighted pointer user has to look at it.
 *
 * ```tsx
 * <QuietActions
 *   actions={
 *     <Button variant="ghost" size="sm" icon={<Icon name="clipboard" />} aria-label={copyThis} />
 *   }
 * >
 *   <Code>{shortDigest(value)}</Code>
 * </QuietActions>
 * ```
 */
export function QuietActions({ actions, gap, children, ...rest }: QuietActionsProps) {
  return (
    <div
      {...rest}
      data-terp="quiet-actions"
      // The gap roll-call's idiom: an unset gap stamps nothing and leaves the base rule
      // standing rather than restating the default in the DOM.
      data-gap={gap === undefined ? undefined : String(gap)}
    >
      {children}
      <div data-terp="quiet-actions-slot">{actions}</div>
    </div>
  );
}
