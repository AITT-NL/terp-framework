import type { HTMLAttributes, ReactNode } from "react";

import type { SpaceToken } from "../layout";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

export interface CardProps
  extends Omit<HTMLAttributes<HTMLElement>, "style" | "title"> {
  /** Optional section heading, rendered as an `<h3>` in the card's header row. */
  title?: UiText;
  /** Optional muted one-liner under the title (what this block is about). */
  description?: UiText;
  /** Optional right-hand slot in the header row (filters, a legend, an action). */
  actions?: ReactNode;
  /** The rendered element — `"section"` by default (a titled block of a page). */
  as?: "section" | "article" | "div" | "aside";
  /** Gap between body children, as a step on the token spacing scale (default `3`). */
  gap?: SpaceToken;
  children?: ReactNode;
}

/**
 * A token-styled surface that groups one block of a page — the sanctioned way to give
 * sections visual separation (border + background + padding) without module CSS, and
 * allowed directly in `OverviewPage` / `DetailPage` body slots under the `standard`
 * layout contract. An optional header row carries a semantic `<h3>` title, a muted
 * description and an `actions` slot; the body stacks its children on the token
 * spacing scale.
 */
export function Card({
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
    <Component {...rest} data-terp="card" data-gap={String(gap)}>
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
