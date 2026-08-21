import type { CSSProperties, ElementType, HTMLAttributes, ReactNode } from "react";

import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

/** The spacing scale — indexes into the `--space-*` design tokens (no arbitrary pixel gaps). */
export type SpaceToken = 0 | 1 | 2 | 3 | 4 | 6 | 8;

/**
 * A value, or one value below the framework's viewport cutover and another above it.
 *
 * There is one cutover and not a scale of them, deliberately: `wide` is the complement of the
 * width at which the shell becomes a drawer and the DataView becomes cards, so a responsive
 * `Stack` changes over at exactly the moment the chrome around it does. A second breakpoint is
 * a rule per value per breakpoint in the sheet, and nothing has asked for one — the same reason
 * the density scale has two steps rather than five.
 */
export type Responsive<T> = T | { narrow: T; wide: T };

/** Split a possibly-responsive prop into its two halves. */
function responsive<T>(value: Responsive<T>): { narrow: T; wide: T | undefined } {
  return value !== null && typeof value === "object" && "narrow" in value
    ? { narrow: value.narrow, wide: value.wide }
    : { narrow: value as T, wide: undefined };
}

export interface StackProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /** The rendered element (`"div"` by default; use `"form"`, `"section"`, `"ul"`, …). */
  as?: ElementType;
  /**
   * Main axis: `"column"` (default) stacks, `"row"` lines up.
   *
   * Takes a {@link Responsive} pair for the toolbar case — `{ narrow: "column", wide: "row" }`
   * is a row of controls that stacks below the cutover, which was previously inexpressible
   * without a `style` an app module may not write.
   */
  direction?: Responsive<"column" | "row">;
  /** Gap between children, as a step on the token spacing scale (default `2`). */
  gap?: Responsive<SpaceToken>;
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
  // A responsive prop is two attributes, and the wide half is stamped only when it was asked
  // for — so a non-responsive Stack renders exactly the attributes it always did and every
  // existing baseline is untouched by construction.
  const directions = responsive(direction);
  const gaps = responsive(gap);
  return (
    <Component
      {...rest}
      data-terp="stack"
      data-direction={directions.narrow}
      data-direction-wide={directions.wide}
      data-gap={String(gaps.narrow)}
      data-gap-wide={gaps.wide === undefined ? undefined : String(gaps.wide)}
      data-wrap={wrap ? "true" : undefined}
      style={alignment}
    />
  );
}

/** Fixed column count, or `"auto"` — as many columns as fit above `minColumn`. */
export type GridColumns = 1 | 2 | 3 | 4 | "auto";

/** Track floor for an `"auto"` grid: the width below which a column stops being one. */
export type GridMinColumn = "xs" | "sm" | "md" | "lg";

export interface GridProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /** The rendered element (`"div"` by default; use `"ul"`, `"section"`, `"dl"`, …). */
  as?: ElementType;
  /**
   * Columns: a fixed count, or `"auto"` (the default) for as many as fit above
   * {@link GridProps.minColumn}.
   *
   * `"auto"` is the responsive answer and it takes no breakpoint: the track floor makes the
   * grid reflow to whatever its **container** can hold, which is what a caller almost always
   * means and is more nearly right than a viewport query — a grid inside a narrow panel
   * should go one-column whatever the window is doing.
   */
  columns?: GridColumns;
  /** Track floor for an `"auto"` grid (default `"sm"`); ignored at a fixed count. */
  minColumn?: GridMinColumn;
  /** Gap between cells, as a step on the token spacing scale (default `4`). */
  gap?: SpaceToken;
  /**
   * Block alignment of each cell within its row (default `"stretch"`).
   *
   * A closed set of four, unlike `Stack`'s `align` — see the note on {@link Grid}.
   */
  align?: "start" | "center" | "end" | "stretch";
  children?: ReactNode;
}

/**
 * The two-dimensional layout primitive, and the one that lifts a real ceiling: with `Stack`
 * as the entire vocabulary, a two-column form could not be expressed at all, so a fifteen-field
 * form shipped as one long vertical run. App modules may not write `style` or `className`
 * (ADR 0059), so that was not awkwardness — it was unbuildable.
 *
 * Every prop is a closed set and becomes a `data-*` attribute with a rule each, so `Grid`
 * renders **no inline style** and stays out of the inline-style ledger (ADR 0097). Three
 * consequences of that are worth knowing, because each was a choice:
 *
 * - **`align` takes four values, where `Stack`'s takes any alignment keyword.** The divergence
 *   is deliberate rather than an oversight. `Stack`'s is open because it was already inline
 *   when ADR 0094 drew the line, and an open vocabulary stays inline; a *new* component picks
 *   the closed set so it needs no `style` at all. `justify` is absent for the same reason it
 *   would be least useful: a grid's tracks already fill their container, so distributing them
 *   is a question about the tracks rather than the cells, and no consumer has asked.
 * - **`minColumn` is a scale, not a length.** `Icon`'s `size` takes any CSS length and stays
 *   inline for it; a grid's column floor could have gone the same way. It is a scale instead
 *   for the reason `Stack`'s `gap` is a token index: so there are no arbitrary widths. An app
 *   wanting 17.5rem cannot have it, which is the same trade `gap` already makes.
 * - **There is no `span`,** and therefore no twelve-column option. A span system needs a child
 *   component to carry it, and a `columns={12}` with no way to span is a grid of twelve narrow
 *   cells rather than a layout system — worse than not offering it.
 */
export function Grid({
  as: Component = "div",
  columns = "auto",
  minColumn = "sm",
  gap = 4,
  align = "stretch",
  ...rest
}: GridProps) {
  return (
    <Component
      {...rest}
      data-terp="grid"
      // The defaults are the base rule, so their attributes match nothing and are left off —
      // the shape density and Button's `md` already use. String(columns) rather than the
      // number, because a `data-` attribute is text and `columns={2}` must produce "2".
      data-columns={columns === "auto" ? undefined : String(columns)}
      data-min-column={columns === "auto" && minColumn !== "sm" ? minColumn : undefined}
      data-gap={String(gap)}
      data-align={align === "stretch" ? undefined : align}
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
