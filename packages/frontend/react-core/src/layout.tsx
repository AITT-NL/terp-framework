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
  /**
   * Inset around the children, as a step on the token spacing scale (default none).
   *
   * The dimension the diagnosis named first — "no padding" — and the one that made a padded
   * region reachable only through a `Card`, whose border and background came with it whether
   * they were wanted or not.
   */
  padding?: SpaceToken;
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
  padding,
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
      data-padding={padding === undefined ? undefined : String(padding)}
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
  /** Inset around the cells, as a step on the token spacing scale (default none). */
  padding?: SpaceToken;
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
  padding,
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
      data-padding={padding === undefined ? undefined : String(padding)}
      data-align={align === "stretch" ? undefined : align}
    />
  );
}

export interface DividerProps extends Omit<HTMLAttributes<HTMLElement>, "style"> {
  /** `"horizontal"` (default) rules across a column; `"vertical"` separates a row. */
  orientation?: "horizontal" | "vertical";
}

/**
 * A rule between two groups of content — `Separator` under its other common name, shipped
 * once rather than twice.
 *
 * An `<hr>`, so the separation is in the accessibility tree rather than only in the pixels; a
 * bordered `<div>` is what a module reaches for when it has no primitive, and it says nothing
 * to a screen reader. The vertical form carries `aria-orientation`, which `<hr>` does not
 * imply.
 *
 * The vertical case needs a height from somewhere and deliberately does not invent one: it
 * stretches to its flex or grid line, so it works between the items of a row `Stack` and is
 * zero-height in a plain block parent. That is the one thing about it worth knowing before
 * reaching for it, and the reason its specimen renders inside a fixed-height row.
 */
export function Divider({ orientation = "horizontal", ...rest }: DividerProps) {
  return (
    <hr
      {...rest}
      data-terp="divider"
      // Horizontal is the base rule, so only the vertical case carries an attribute.
      data-orientation={orientation === "vertical" ? "vertical" : undefined}
      aria-orientation={orientation === "vertical" ? "vertical" : undefined}
    />
  );
}

export interface DetailItem {
  /** The item's label (rendered as `<dt>`). */
  label: UiText;
  /** The item's value (rendered as `<dd>`). */
  value: ReactNode;
}

/** How a pair is arranged. */
export type DetailListLayout = "inline" | "aligned" | "stacked";

export interface DetailListProps extends Omit<HTMLAttributes<HTMLDListElement>, "style"> {
  /** The label/value pairs to render, in order. */
  items: readonly DetailItem[];
  /**
   * How each pair reads (default `"inline"` — `Label: value` on one line).
   *
   * `"aligned"` puts every label in a shared left column, so the values line up; `"stacked"`
   * puts the label above its value, which is what a narrow column or a long value wants.
   *
   * The default is the old behaviour on purpose: this component is in the `standard` layout
   * contract's detail-page slot, so every governed detail screen already renders one.
   */
  layout?: DetailListLayout;
  /** Pairs per row (default `1`). */
  columns?: 1 | 2;
  /**
   * Distance **between pairs**, as a step on the token spacing scale.
   *
   * Defaults to the layout's own: `--space-3` for `aligned` and `stacked`, `--space-1` for
   * `inline`, where a pair is one line of a paragraph rather than a block of its own.
   *
   * It sets the ROW gap only, and that is a guarantee rather than an implementation detail. The
   * column gap is the label-to-value distance in `aligned` and the space between pair groups at
   * `columns={2}`, so a caller who could set it would be reaching past the layout into its
   * internals; a `gap` shorthand from here would reset both.
   *
   * The prop exists because its absence was the reason the value was unreachable: `Stack`,
   * `Grid` and `Card` all take a `gap` on this scale, and app modules may write neither `style`
   * nor `className` (ADR 0059), so a detail list needing looser rows had nowhere to say so.
   */
  gap?: SpaceToken;
}

/**
 * Token-styled label/value pairs as a semantic `<dl>` — record metadata on a detail page,
 * an expanded row's summary.
 *
 * A real grid rather than an inline run, which is the thing the diagnosis was pointing at: nine
 * pairs including two 64-character digests, "through an inline run 4px apart with no
 * alignment". Two fixes rather than one, and the second was the actual defect:
 *
 * - `layout="aligned"` gives the labels a shared column. The row wrapper becomes
 *   `display: contents` so the `<dt>` and `<dd>` are grid items of the `<dl>` itself — no DOM
 *   change, and the only way to align across rows without one.
 * - **The tracks are floored at zero.** An implicit grid column is `auto`, which floors at
 *   *min-content* — so a 64-character digest with nothing to break on widened the column and
 *   pushed the list past its container. `minmax(0, 1fr)` is what stops that, and it is the same
 *   declaration `Grid`'s fixed counts need for the same reason.
 *
 * The colon lives in the sheet rather than in the markup, because it belongs to the inline
 * layout alone — `aligned` and `stacked` must not have one, and a text node cannot be
 * withdrawn by a rule. It is decorative either way: the `<dt>` / `<dd>` pairing is what carries
 * the relationship to assistive tech.
 *
 * Three later corrections are worth knowing, because each was measured rather than reasoned:
 *
 * - **The label is muted, and `aligned` shares that rule with `stacked`.** It did not, and the
 *   gap was the whole legibility complaint: an aligned `<dt>` rendered at the value's own size,
 *   weight and ink, so a card of five labelled values was a wall of bold text with nothing
 *   saying which half to read first. `inline` keeps its plain term deliberately — there the
 *   label is half a sentence.
 * - **Rows are `--space-3` apart in both non-inline layouts.** At the old `--space-1` the
 *   distance within a pair equalled the distance between pairs, so nothing grouped. {@link
 *   DetailListProps.gap} makes it a caller's choice on the same scale as every other primitive.
 * - **It reflows to one column below the framework's viewport cutover**, where `Grid`
 *   deliberately does not for a fixed `columns` count. The asymmetry is a decision: `Grid`
 *   publishes `columns="auto"` as its responsive answer and this component's closed `1 | 2` has
 *   no such escape, so the reflow has to be its own. Above the cutover the shape is what it
 *   was, bar a label column now capped at `max-content` rather than floored at min-content;
 *   below it, four tracks in a phone's width met `overflow-wrap: anywhere` — correct for an
 *   unbreakable digest, wrong as a way to fit a label — and broke ordinary values mid-word.
 */
export function DetailList({
  items,
  layout = "inline",
  columns = 1,
  gap,
  ...rest
}: DetailListProps) {
  const text = useUiText();
  return (
    <dl
      {...rest}
      data-terp="detail-list"
      // `inline` and one column are the base rule, so neither stamps an attribute.
      data-layout={layout === "inline" ? undefined : layout}
      data-columns={columns === 1 ? undefined : String(columns)}
      // No default to compare against: the default row gap is the LAYOUT's, so an unset gap
      // must stamp no attribute at all and leave the layout rule standing. Stack's and Grid's
      // gaps stamp unconditionally because their defaults are one value, not three.
      data-gap={gap === undefined ? undefined : String(gap)}
    >
      {items.map((item, index) => (
        <div key={index} data-terp="detail-list-row">
          <dt data-terp="detail-list-term">{text(item.label)}</dt>
          <dd data-terp="detail-list-value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
