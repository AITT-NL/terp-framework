import type { CSSProperties, ElementType, HTMLAttributes, ReactNode } from "react";

import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

/** The spacing scale — indexes into the `--space-*` design tokens (no arbitrary pixel gaps). */
export type SpaceToken = 0 | 1 | 2 | 3 | 4 | 6 | 8;

export interface StackProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /** The rendered element (`"div"` by default; use `"form"`, `"section"`, `"ul"`, …). */
  as?: ElementType;
  /** Main axis: `"column"` (default) stacks, `"row"` lines up. */
  direction?: "column" | "row";
  /** Gap between children, as a step on the token spacing scale (default `2`). */
  gap?: SpaceToken;
  /** Cross-axis alignment (e.g. `"center"`, `"start"`, `"end"`, `"stretch"`). */
  align?: CSSProperties["alignItems"];
  /** Main-axis distribution (e.g. `"space-between"`, `"center"`, `"end"`). */
  justify?: CSSProperties["justifyContent"];
  /** Allow row items to wrap onto new lines (rows of tags, toolbars). */
  wrap?: boolean;
  children?: ReactNode;
}

/**
 * The layout primitive: a flex container whose gap comes from the token spacing scale, so
 * app modules compose layout **without writing CSS or `style={}`** (the boundary lint refuses
 * the `style` attribute in module code). A vertical `Stack` lays out a form; a `row` Stack
 * with `justify="space-between"` is a toolbar. Anything more bespoke belongs in a react-core
 * component, not ad-hoc styles in a module.
 */
export function Stack({
  as: Component = "div",
  direction = "column",
  gap = 2,
  align,
  justify,
  wrap = false,
  ...rest
}: StackProps) {
  // `direction`, `gap` and `wrap` are closed sets, so they are attributes the sheet keys
  // on. `align` and `justify` take any alignment keyword CSS accepts, so they stay inline
  // rather than turning an open vocabulary into a rule per value (ADR 0094). Undefined on
  // both means no style attribute at all.
  const alignment: CSSProperties | undefined =
    align === undefined && justify === undefined
      ? undefined
      : {
          ...(align !== undefined ? { alignItems: align } : undefined),
          ...(justify !== undefined ? { justifyContent: justify } : undefined),
        };
  return (
    <Component
      {...rest}
      data-terp="stack"
      data-direction={direction}
      data-gap={String(gap)}
      data-wrap={wrap ? "true" : undefined}
      style={alignment}
    />
  );
}

export interface DetailItem {
  /** The item's label (rendered as `<dt>`). */
  label: UiText;
  /** The item's value (rendered as `<dd>`). */
  value: ReactNode;
}

export interface DetailListProps extends Omit<HTMLAttributes<HTMLDListElement>, "style"> {
  /** The label/value pairs to render, in order. */
  items: readonly DetailItem[];
}

/**
 * Token-styled label/value pairs as a semantic `<dl>` — record metadata on a detail page,
 * an expanded row's summary. Centralizes the "Label: value" pattern so modules never
 * hand-style definition lists.
 */
export function DetailList({ items, ...rest }: DetailListProps) {
  const text = useUiText();
  return (
    <dl {...rest} data-terp="detail-list">
      {items.map((item, index) => (
        <div key={index}>
          <dt data-terp="detail-list-term">{text(item.label)}: </dt>
          <dd data-terp="detail-list-value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
