import { useId } from "react";

import { useFormatNumber } from "../format";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { PLOT_HEIGHT, PLOT_WIDTH, bandCentre, columnOf, valueAxis, xOf, yOf } from "./scale";
import type { ValueAxis } from "./scale";

injectTerpStyles();

/** One point of a series, or one bar: what it is, and how much. */
export interface ChartPoint {
  /** What the point is — a period's name or a date in a trend, a category in a bar chart. */
  label: UiText;
  /** How much, in the chart's format. A value that is not a number is printed as the dash and drawn as a gap. */
  value: number;
}

/** A named run of points, oldest first. */
export interface ChartSeries {
  /** What the series is ("This month"): its legend entry and its column in the table. */
  label: UiText;
  points: readonly ChartPoint[];
}

/** How the series is drawn: a line, a line with the area under it filled, or a column per point. */
export type TrendMark = "line" | "area" | "columns";

export interface TrendChartProps {
  /** What the chart shows: printed as its caption, and its accessible name. */
  label: UiText;
  /** The values over time. */
  series: ChartSeries;
  /**
   * The same measure for an earlier period, drawn as a dashed line — behind a line or an area,
   * over columns, where behind them it would be hidden — and listed beside the series in the
   * table: the comparison a figure's delta summarises. Point `i` of
   * either series stands at the same place, so a period still running stops short of the one it
   * is compared with, as "this month so far" against last month should. Where the two differ in
   * length, label points by their place in the period ("Day 3"): the axis and the table read a
   * point's label from whichever series has that point.
   */
  comparison?: ChartSeries;
  /**
   * `"line"` (the default) for a level that moves, `"area"` for an amount that accumulates,
   * `"columns"` for a count per period — runs per day, deliveries per hour. An area and columns
   * keep zero on the axis, because their length is the value; a line does not, because an axis
   * from zero flattens the change a line is drawn to show.
   */
  mark?: TrendMark;
  /** How values print, as `Intl.NumberFormatOptions` (default: a plain number). */
  format?: Intl.NumberFormatOptions;
}

/**
 * Points as runs of coordinates, broken where a value is not a number. `x` places point `i`;
 * a run of one point is kept, and drawn as a dot, since a line needs two.
 */
function runsOf(points: readonly ChartPoint[], axis: ValueAxis, x: (index: number) => number): string[][] {
  const runs: string[][] = [];
  let current: string[] = [];
  points.forEach((point, index) => {
    if (!Number.isFinite(point.value)) {
      if (current.length > 0) runs.push(current);
      current = [];
      return;
    }
    current.push(`${x(index)},${yOf(point.value, axis)}`);
  });
  if (current.length > 0) runs.push(current);
  return runs;
}

/**
 * Values over time (ADR 0158, ADR 0169 §6): a line, an area or columns, with an optional
 * comparison period, on a value axis of round numbers.
 *
 * Under ADR 0158's contract: SVG geometry in attributes and colour from the sheet, so nothing
 * is styled inline; numbers through the `format` helpers in the app's locale; no dependency;
 * and the data as a table — visually hidden here, read by assistive technology in place of the
 * picture, which is hidden from it. The axis takes three ticks in two equal steps, so its labels
 * stand at the top, the middle and the foot of the plot without a position of their own; an
 * axis of counts steps in whole numbers.
 *
 * A tile on the surface, the rung where data is read (ADR 0169 §3), like a figure.
 */
export function TrendChart({ label, series, comparison, mark = "line", format }: TrendChartProps) {
  const resolve = useUiText();
  const formatNumber = useFormatNumber();
  const captionId = useId();
  const points = series.points;
  const earlier = comparison?.points ?? [];
  // One index scale for both series, as long as the longer of them.
  const count = Math.max(points.length, earlier.length);
  const values = [...points, ...earlier].map((point) => point.value);
  const counts = values.filter((value) => Number.isFinite(value)).every((value) => Number.isInteger(value));
  const axis = valueAxis(values, mark !== "line", counts);
  const base = yOf(Math.min(Math.max(0, axis.low), axis.high), axis);
  // A line's point stands at its index across the plot; a column's in the middle of its band,
  // where a comparison drawn over columns puts its vertices too.
  const x = mark === "columns" ? (index: number) => bandCentre(index, count) : (index: number) => xOf(index, count);
  const lines = runsOf(points, axis, x);
  const before = runsOf(earlier, axis, x);
  const caption = resolve(label);
  const labelAt = (index: number) => resolve(points[index]?.label ?? earlier[index]?.label ?? "");
  // Which labels the x axis prints: the ends, and the middle where there are enough points for
  // one. A column chart prints under its columns, so its middle band always has one; a line's
  // middle label sits at the plot's centre, where only an odd number of points puts a point.
  const middle = (count - 1) / 2;
  const shown = (index: number) =>
    index === 0 ||
    index === count - 1 ||
    (count >= 5 && (mark === "columns" ? index === Math.floor(middle) : index === middle));
  const indices = Array.from({ length: count }, (_, index) => index);
  const comparisonMarks = before.map((run, index) =>
    run.length === 1 ? (
      // A zero-length stroke with a round cap: a dot the plot's stretch cannot flatten.
      <polyline key={`c${index}`} data-terp="trend-chart-dot" data-series="comparison" points={`${run[0]} ${run[0]}`} />
    ) : (
      <polyline key={`c${index}`} data-terp="trend-chart-comparison" points={run.join(" ")} />
    ),
  );
  return (
    // Named by its caption explicitly: the figure-from-figcaption name is the HTML mapping
    // browsers implement and not every accessibility tree computes.
    <figure data-terp="trend-chart" data-mark={mark} aria-labelledby={captionId}>
      <figcaption id={captionId} data-terp="chart-caption">
        {caption}
      </figcaption>
      {comparison !== undefined && (
        <ul data-terp="chart-legend">
          <li data-terp="chart-legend-item">
            <span data-terp="chart-swatch" data-series="main" aria-hidden="true" />
            {resolve(series.label)}
          </li>
          <li data-terp="chart-legend-item">
            <span data-terp="chart-swatch" data-series="comparison" aria-hidden="true" />
            {resolve(comparison.label)}
          </li>
        </ul>
      )}
      <div data-terp="chart-body" aria-hidden="true">
        <span data-terp="chart-axis">
          {axis.ticks.map((tick, index) => (
            <span key={index}>{formatNumber(tick, format)}</span>
          ))}
        </span>
        <svg
          data-terp="chart-plot"
          viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`}
          preserveAspectRatio="none"
          focusable="false"
        >
          {[0, PLOT_HEIGHT / 2, PLOT_HEIGHT].map((y) => (
            <line key={y} data-terp="chart-gridline" x1={0} x2={PLOT_WIDTH} y1={y} y2={y} />
          ))}
          {mark !== "columns" && comparisonMarks}
          {mark === "area" &&
            lines
              .filter((run) => run.length > 1)
              .map((run, index) => {
                const first = run[0]!.split(",")[0];
                const last = run.at(-1)!.split(",")[0];
                return (
                  <polygon
                    key={index}
                    data-terp="trend-chart-area"
                    points={`${first},${base} ${run.join(" ")} ${last},${base}`}
                  />
                );
              })}
          {mark !== "columns" &&
            lines.map((run, index) =>
              run.length === 1 ? (
                <polyline key={index} data-terp="trend-chart-dot" points={`${run[0]} ${run[0]}`} />
              ) : (
                <polyline key={index} data-terp="trend-chart-line" points={run.join(" ")} />
              ),
            )}
          {mark === "columns" &&
            points.map((point, index) => {
              if (!Number.isFinite(point.value)) {
                return null;
              }
              const column = columnOf(index, count);
              const y = yOf(point.value, axis);
              return (
                <rect
                  key={index}
                  data-terp="trend-chart-column"
                  x={column.x}
                  y={Math.min(y, base)}
                  width={column.width}
                  height={Math.abs(base - y)}
                />
              );
            })}
          {mark === "columns" && comparisonMarks}
        </svg>
        <span data-terp="chart-labels" data-mark={mark}>
          {indices.map((index) =>
            mark === "columns" || shown(index) ? (
              <span key={index} data-quiet={mark === "columns" && !shown(index) ? "true" : undefined}>
                {labelAt(index)}
              </span>
            ) : null,
          )}
        </span>
      </div>
      {/* Named by the same caption rather than a <caption> of its own, so it is not read twice. */}
      <table data-terp="chart-table" aria-labelledby={captionId}>
        <thead>
          <tr>
            <td />
            <th scope="col">{resolve(series.label)}</th>
            {comparison !== undefined && <th scope="col">{resolve(comparison.label)}</th>}
          </tr>
        </thead>
        <tbody>
          {indices.map((index) => (
            <tr key={index}>
              <th scope="row">{labelAt(index)}</th>
              <td>{formatNumber(points[index]?.value, format)}</td>
              {comparison !== undefined && <td>{formatNumber(earlier[index]?.value, format)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
