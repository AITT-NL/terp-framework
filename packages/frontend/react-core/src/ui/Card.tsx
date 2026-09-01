import type { HTMLAttributes, ReactNode } from "react";

import type { SpaceToken } from "../layout";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

/** Chrome, or none: `"plain"` keeps the heading and drops the box. */
export type CardVariant = "boxed" | "plain";

export interface CardProps
  extends Omit<HTMLAttributes<HTMLElement>, "style" | "title"> {
  /**
   * Whether the block carries a box (default `"boxed"`) or just its heading (`"plain"`).
   *
   * `"plain"` is the labelled-region case: a titled group inside something that is already a
   * surface, where a second border reads as a frame around a frame. The commonest instance is
   * a section whose body is a `DataView` — boxed, the table gets a border inside a border and
   * loses its full width.
   *
   * It is a variant rather than a `Section` component of its own, and that is a decision worth
   * knowing. A chrome-less titled region is exactly this element with two declarations
   * removed: `Card` already renders a `<section>` with an `<h3>` and stacks its children on
   * the token scale. A second component would have meant six more markers describing the same
   * DOM, and a `Surface` — the third name the diagnosis suggested — is a `Card` with no title,
   * which this already is. Two names for one box is the `LoadingButton` mistake.
   */
  variant?: CardVariant;
  /** Optional section heading, rendered as an `<h3>` in the card's header row. */
  title?: UiText;
  /** Optional muted one-liner under the title (what this block is about). */
  description?: UiText;
  /**
   * Optional right-hand slot in the header row (filters, a legend, an action).
   *
   * It stays on the title's line whether or not there is a {@link CardProps.description}, and
   * that took a rule rather than coming for free: the header wraps, and a heading block sized
   * from its content is as wide as its longest line — a description sentence — so flex broke
   * the line before it shrank anything and the slot landed underneath. Measured at a 103px
   * header against 48px for the same component with the description removed. The heading's
   * flex base is 0 now, so both fit on one line by construction, and the header aligns to
   * `start` once a description is present so the control sits beside the title rather than
   * floating in the middle of the block.
   */
  actions?: ReactNode;
  /** The rendered element — `"section"` by default (a titled block of a page). */
  as?: "section" | "article" | "div" | "aside";
  /** Gap between body children, as a step on the token spacing scale (default `3`). */
  gap?: SpaceToken;
  children?: ReactNode;
}

/**
 * A token-styled frame that groups one block of a page — the sanctioned way to give
 * sections visual separation (a border, a radius and padding) without module CSS, and
 * allowed directly in `OverviewPage` / `DetailPage` body slots under the `standard`
 * layout contract. It carries no fill: what shows through a card is the page's own
 * canvas, so a card sits on a themed background instead of repainting it. An optional header row carries a semantic `<h3>` title, a muted
 * description and an `actions` slot; the body stacks its children on the token
 * spacing scale.
 */
export function Card({
  variant = "boxed",
  title,
  description,
  actions,
  as: Component = "section",
  gap = 3,
  children,
  ...rest
}: CardProps) {
  const resolve = useUiText();
  const hasHeader = title !== undefined || actions !== undefined;
  return (
    <Component
      {...rest}
      data-terp="card"
      // `boxed` is the base rule, so its attribute would describe the default twice — the
      // idiom density, Button's `md` and Grid's `auto` all use.
      data-variant={variant === "boxed" ? undefined : variant}
      data-gap={String(gap)}
    >
      {hasHeader ? (
        <div data-terp="card-header">
          <div data-terp="card-heading">
            {title !== undefined ? <h3 data-terp="card-title">{resolve(title)}</h3> : null}
            {description !== undefined ? (
              <p data-terp="card-description">{resolve(description)}</p>
            ) : null}
          </div>
          {actions !== undefined ? (
            <div data-terp="card-actions">
              {actions}
            </div>
          ) : null}
        </div>
      ) : description !== undefined ? (
        <p data-terp="card-description">{resolve(description)}</p>
      ) : null}
      {children}
    </Component>
  );
}
