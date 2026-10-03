import { useId } from "react";

import { useFormatNumber } from "../format";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import type { ChartPoint } from "./TrendChart";
import { round } from "./scale";

injectTerpStyles();

export interface BarChartProps {
  /** What the bars compare: printed as the chart's caption, and its accessible name. */
  label: UiText;
  /**
   * The categories, in the order to show them. Rank them before passing them: the order is the
   * reading, and a chart that sorted on its own would answer a question the caller did not ask.
   */
  bars: readonly ChartPoint[];
  /** How values print, as `Intl.NumberFormatOptions` (default: a plain number). */
  format?: Intl.NumberFormatOptions;
  /** The top of every bar's range (default: the largest value). */
  max?: number;
}

/**
 * Categories compared by length (ADR 0158, ADR 0169 §6): one row per category, its name, its
 * bar and its value, the bars scaled to the largest.
 *
 * The chart IS its table. ADR 0158 asks every chart for its data as a table, and a bar chart's
 * data is one row per bar — so the rows are a `<table>`, named by the caption, with each
 * category as a row header and each value printed, and the bar is a cell of its own drawn for
 * the eye and hidden from assistive technology with its cell, so a row reads as its name and
 * its value and never as a blank between them. A name longer than a third of the tile ends in
 * an ellipsis rather than squeezing the bars; its whole text is still what is read.
 *
 * The bars are SVG geometry with the chart's first colour from the sheet, so nothing is styled
 * inline, and a value that is not a number draws no bar and prints the dash.
 */
export function BarChart({ label, bars, format, max }: BarChartProps) {
  const resolve = useUiText();
  const formatNumber = useFormatNumber();
  const captionId = useId();
  const finite = bars.map((bar) => bar.value).filter((value) => Number.isFinite(value));
  const top = max ?? Math.max(0, ...finite);
  return (
    <figure data-terp="bar-chart" aria-labelledby={captionId}>
      <figcaption id={captionId} data-terp="chart-caption">
        {resolve(label)}
      </figcaption>
      <table data-terp="bar-chart-table" aria-labelledby={captionId}>
        <tbody>
          {bars.map((bar, index) => {
            const share =
              top > 0 && Number.isFinite(bar.value) ? Math.min(Math.max(bar.value / top, 0), 1) : 0;
            return (
              <tr key={index}>
                <th scope="row" data-terp="bar-chart-label">
                  <span data-terp="bar-chart-name">{resolve(bar.label)}</span>
                </th>
                <td data-terp="bar-chart-bar" aria-hidden="true">
                  <svg viewBox="0 0 100 1" preserveAspectRatio="none" focusable="false">
                    <rect data-terp="bar-chart-mark" x={0} y={0} width={round(share * 100)} height={1} />
                  </svg>
                </td>
                <td data-terp="bar-chart-value">{formatNumber(bar.value, format)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </figure>
  );
}
