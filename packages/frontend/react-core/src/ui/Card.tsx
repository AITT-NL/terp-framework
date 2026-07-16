import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

import type { SpaceToken } from "../layout";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";

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

const cardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  padding: "var(--space-4)",
  minWidth: 0,
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: "var(--space-3)",
};

const titleStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-md)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
  lineHeight: 1.3,
};

const descriptionStyle: CSSProperties = {
  margin: 0,
  color: "var(--color-neutral-600)",
  fontSize: "var(--font-size-sm)",
};

/**
 * A token-styled surface that groups one block of a page — the sanctioned way to give
 * sections visual separation (border + background + padding) without module CSS. An
 * optional header row carries a semantic `<h3>` title, a muted description and an
 * `actions` slot; the body stacks its children on the token spacing scale.
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
    <Component {...rest} data-terp="card" style={{ ...cardStyle, gap: `var(--space-${gap})` }}>
      {hasHeader ? (
        <div data-terp="card-header" style={headerStyle}>
          <div style={{ minWidth: 0 }}>
            {title !== undefined ? <h3 style={titleStyle}>{resolve(title)}</h3> : null}
            {description !== undefined ? (
              <p style={descriptionStyle}>{resolve(description)}</p>
            ) : null}
          </div>
          {actions !== undefined ? (
            <div data-terp="card-actions" style={{ flexShrink: 0 }}>
              {actions}
            </div>
          ) : null}
        </div>
      ) : description !== undefined ? (
        <p style={descriptionStyle}>{resolve(description)}</p>
      ) : null}
      {children}
    </Component>
  );
}
