import { useId } from "react";

import { useFormatNumber } from "../format";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { PLOT_HEIGHT, PLOT_WIDTH, columnOf, valueAxis, xOf, yOf } from "./scale";

injectTerpStyles();

/** One point of a series: when, and how much. */
export interface ChartPoint {
  /** When — a period's name or a formatted date. */
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
   * The same measure for an earlier period, drawn as a dashed line behind the series and
   * listed beside it in the table — the comparison a figure's delta summarises.
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

/** Points as a polyline's coordinates, a gap where a value is not a number. */
function polyline(points: readonly ChartPoint[], axis: ReturnType<typeof valueAxis>): string[] {
  const runs: string[] = [];
  let current: string[] = [];
  points.forEach((point, index) => {
    if (!Number.isFinite(point.value)) {
      if (current.length > 0) runs.push(current.join(" "));
      current = [];
      return;
    }
    current.push(`${xOf(index, points.length)},${yOf(point.value, axis)}`);
  });
  if (current.length > 0) runs.push(current.join(" "));
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
 * stand at the top, the middle and the foot of the plot without a position of their own.
 *
 * A tile on the surface, the rung where data is read (ADR 0169 §3), like a figure.
 */
export function TrendChart({ label, series, comparison, mark = "line", format }: TrendChartProps) {
  const resolve = useUiText();
  const formatNumber = useFormatNumber();
  const captionId = useId();
  const points = series.points;
  const earlier = comparison?.points ?? [];
  const axis = valueAxis(
    [...points.map((point) => point.value), ...earlier.map((point) => point.value)],
    mark !== "line",
  );
  const base = yOf(Math.min(Math.max(0, axis.low), axis.high), axis);
  const lines = polyline(points, axis);
  const caption = resolve(label);
  // Which labels the x axis prints: the ends, and the middle where there are enough points
  // for one. Columns print theirs under each column, the rest held in place but not drawn.
  const middle = Math.floor((points.length - 1) / 2);
  const shown = (index: number) =>
    index === 0 || index === points.length - 1 || (points.length >= 5 && index === middle);
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
          {comparison !== undefined &&
            polyline(earlier, axis).map((run, index) => (
              <polyline key={index} data-terp="trend-chart-comparison" points={run} />
            ))}
          {mark === "area" &&
            lines.map((run, index) => {
              const first = run.split(" ")[0]!.split(",")[0];
              const last = run.split(" ").at(-1)!.split(",")[0];
              return (
                <polygon
                  key={index}
                  data-terp="trend-chart-area"
                  points={`${first},${base} ${run} ${last},${base}`}
                />
              );
            })}
          {mark !== "columns" &&
            lines.map((run, index) => (
              <polyline key={index} data-terp="trend-chart-line" points={run} />
            ))}
          {mark === "columns" &&
            points.map((point, index) => {
              if (!Number.isFinite(point.value)) {
                return null;
              }
              const { x, width } = columnOf(index, points.length);
              const y = yOf(point.value, axis);
              return (
                <rect
                  key={index}
                  data-terp="trend-chart-column"
                  x={x}
                  y={Math.min(y, base)}
                  width={width}
                  height={Math.abs(base - y)}
                />
              );
            })}
        </svg>
        <span data-terp="chart-labels" data-mark={mark}>
          {points.map((point, index) =>
            mark === "columns" || shown(index) ? (
              <span key={index} data-quiet={mark === "columns" && !shown(index) ? "true" : undefined}>
                {resolve(point.label)}
              </span>
            ) : null,
          )}
        </span>
      </div>
      <table data-terp="chart-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <td />
            <th scope="col">{resolve(series.label)}</th>
            {comparison !== undefined && <th scope="col">{resolve(comparison.label)}</th>}
          </tr>
        </thead>
        <tbody>
          {points.map((point, index) => (
            <tr key={index}>
              <th scope="row">{resolve(point.label)}</th>
              <td>{formatNumber(point.value, format)}</td>
              {comparison !== undefined && <td>{formatNumber(earlier[index]?.value, format)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
