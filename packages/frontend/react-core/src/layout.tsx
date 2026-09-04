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
  /**
   * Give this pair the whole row, across every track (default `false`).
   *
   * The escape from the shared column, for the one pair that cannot live in it: a paragraph, a
   * payload, a code block, a value whose label is short and whose content is a screen wide. The
   * label goes above the value and the pair spans the list, exactly as the same pair renders
   * below the viewport cutover — so this is the narrow shape, asked for at one row rather than
   * imposed on all of them.
   *
   * It exists because the alternative was a SECOND list. A card holding eight aligned pairs and
   * one wide value had to close the `<dl>`, render the wide thing, and open another — which
   * gives the two lists two independently measured label columns, so the values in each land on
   * a different vertical line. One `full` row keeps one list, one measure, one column.
   *
   * It spans TRACKS, so it does nothing where there are none to span: `layout="inline"` at
   * `columns={1}`, and every layout below the cutover, are already one full-width column. That
   * is not a silent no-op to work around — it is the same pair rendering the same way for a
   * different reason.
   */
  full?: boolean;
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
  /**
   * Pairs per row: `1` (default), `2`, or `"auto"` to follow the available width.
   *
   * `"auto"` is the answer to the asymmetry this component's own notes below record: `Grid`
   * publishes `columns="auto"` and a closed one-or-two had no such escape, so a detail list
   * that wanted to be two columns on a desk and one on a phone got a hand-rolled reflow at the
   * framework's single viewport cutover. `"auto"` needs no cutover at all — the track floor
   * decides, so the list follows its CONTAINER rather than the window, which is the difference
   * that matters for a list inside a card inside a split pane.
   *
   * The floors are published here because they are the whole behaviour: a pair is at least
   * `9rem` of label and `13rem` of value, so 22rem, and each floor is additionally capped at a
   * share of the track (30% and 60%) so that ONE pair always fits a narrow container instead of
   * overflowing it. Measured across seven widths: three pairs at 1200px, two at 900px, one from
   * 700px down, and no sideways scroll at 240px. `"auto"` on `inline` or `stacked` repeats one
   * track per pair at `Grid`'s own `16rem` floor, since there is no label column to size.
   *
   * The closed counts keep the cutover reflow — `1` and `2` say a number, and a number that
   * silently became three would not be one.
   */
  columns?: 1 | 2 | "auto";
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
 *   deliberately does not for a fixed `columns` count. The asymmetry was a decision and is now
 *   half retired: {@link DetailListProps.columns} takes `"auto"`, which follows the available
 *   width with no cutover at all, and the closed counts keep the reflow because a number that
 *   silently became three would not be a number. Above the cutover the shape is what it
 *   was, bar a label column now capped at `max-content` rather than floored at min-content;
 *   below it, four tracks in a phone's width met `overflow-wrap: anywhere` — correct for an
 *   unbreakable digest, wrong as a way to fit a label — and broke ordinary values mid-word.
 *
 * Two later additions are about the shared column rather than the pairs, and both exist because
 * the alternative was splitting the list:
 *
 * - **{@link DetailItem.full} gives one pair the whole row.** A wide value — a paragraph, a
 *   payload — used to require closing the `<dl>` and opening another, which is two measured
 *   label columns and therefore two vertical lines for the values to land on.
 * - **{@link DetailListGroup} shares one measure across several lists**, for the case where the
 *   lists must stay separate: their own headings, their own order, other content between them.
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
        <div
          key={index}
          data-terp="detail-list-row"
          // Absent rather than "false", the sheet's own idiom: the default stamps nothing, so
          // the rule needs no negative selector and the DOM says only what is true of it.
          data-full={item.full === true ? "true" : undefined}
        >
          <dt data-terp="detail-list-term">{text(item.label)}</dt>
          <dd data-terp="detail-list-value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface DetailListGroupProps extends Omit<HTMLAttributes<HTMLDivElement>, "style"> {
  /**
   * Distance between the lists, as a step on the token spacing scale (default `--space-4`).
   *
   * The ROW gap only, like {@link DetailListProps.gap} and for the same reason: the column gap
   * is the shared label-to-value distance, and a caller who could set it here would be moving
   * every nested list's internal measure from the outside.
   */
  gap?: SpaceToken;
  /** The lists, and anything that belongs between them. */
  children: ReactNode;
}

/**
 * Several {@link DetailList}s that share ONE measured label column.
 *
 * The friction it removes: a card that shows a record in sections — "Identity", "Schedule",
 * "What it reported" — renders a list per section, because the sections have their own headings
 * and their own order and one `<dl>` cannot carry that. Each list then measures its own label
 * column, so the values in each land on a different vertical line: four lists, four gutters,
 * on one card. Nothing is misaligned by any single list's own rules, which is why it reads as
 * sloppy rather than broken and why no test could have caught it.
 *
 * The mechanism is `subgrid`, and this wrapper is what makes it possible: the GROUP owns the
 * track list, each aligned list inside becomes `grid-template-columns: subgrid`, and every
 * label in every list is then measured against the same track. Measured: three lists whose
 * labels differ in width put all three values at the same pixel.
 *
 * **Explicit rather than inferred**, which is the design decision worth stating. This could
 * have been something `Card` did to the lists it happens to contain, and then a card that
 * deliberately wants two differently-sized label columns would have no way to say so — and a
 * card would know about `<dl>` tracks, which is a layer it has no business in.
 *
 * Three limits, each of them the honest kind:
 *
 * - **It shares the measure for `layout="aligned"` lists at the default single column**, since
 *   that is the only shape that HAS a shared label column. A `columns={2}` list keeps its own
 *   four tracks rather than being quietly folded into two — its pairs would otherwise reflow to
 *   one per row, which is a layout change disguised as an alignment fix.
 * - **Above the viewport cutover only.** Below it every list is one column with the label above
 *   its value, so there is no column to share; the group is then a plain stack of lists.
 * - **It degrades to exactly today's output.** Without `subgrid` each list keeps its own tracks,
 *   which is what it renders now, so this ships with no feature query and no fallback branch.
 *   Baseline-wide since Chrome 117 / Safari 16 / Firefox 71.
 *
 * Children other than lists are welcome and span the whole group — a `Text` heading between two
 * lists, a `Divider` — which is the other half of why this is a wrapper and not a prop.
 */
export function DetailListGroup({ gap, children, ...rest }: DetailListGroupProps) {
  return (
    <div
      {...rest}
      data-terp="detail-list-group"
      // The gap roll-call's idiom, and DetailList's: an unset gap stamps nothing and leaves the
      // base rule standing, so there is no default to compare against.
      data-gap={gap === undefined ? undefined : String(gap)}
    >
      {children}
    </div>
  );
}
