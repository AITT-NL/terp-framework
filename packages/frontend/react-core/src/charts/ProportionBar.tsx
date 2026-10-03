import { useId } from "react";

import { useFormatNumber } from "../format";
import { injectTerpStyles } from "../styles";
import type { BadgeTone } from "../ui/Badge";
import { useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { round } from "./scale";

injectTerpStyles();

/** One part of a whole. */
export interface ProportionPart {
  /** What the part is ("Created"): its legend entry. */
  label: UiText;
  /** How many. Parts that are not positive numbers take no share. */
  value: number;
  /**
   * The part's tone where it is a state — created, updated, failed — so failed reads as the
   * danger it is; parts without one take the chart colours in order.
   */
  tone?: BadgeTone;
}

export interface ProportionBarProps {
  /** What the whole is: printed as the caption, and the accessible name. */
  label: UiText;
  /** The parts, in the order they lie along the bar. */
  parts: readonly ProportionPart[];
  /** How each part's count prints, as `Intl.NumberFormatOptions` (default: a plain number). */
  format?: Intl.NumberFormatOptions;
}

// One decimal, so a small part reads as the half a percent it is rather than as nothing.
const PERCENT: Intl.NumberFormatOptions = { style: "percent", maximumFractionDigits: 1 };

/**
 * A whole split into its parts (ADR 0169 §6): one bar, each part's length its share, and a
 * legend that says every part in words — its name, its count and its share. The legend is the
 * chart's data and the bar is hidden from assistive technology, so a tone is always also a word.
 *
 * Parts that are states take their tone; the rest take the chart colours in order. Adjacent
 * parts are parted by a hairline of the surface, so two parts of near colours still read as two.
 */
export function ProportionBar({ label, parts, format }: ProportionBarProps) {
  const resolve = useUiText();
  const formatNumber = useFormatNumber();
  const captionId = useId();
  const counted = parts.map((part) => (Number.isFinite(part.value) && part.value > 0 ? part.value : 0));
  const total = counted.reduce((sum, value) => sum + value, 0);
  let start = 0;
  const segments = counted.map((value) => {
    const width = total > 0 ? (value / total) * 100 : 0;
    const segment = { x: round(start), width: round(width) };
    start += width;
    return segment;
  });
  // A part with no tone of its own takes the next chart colour.
  const series = (index: number) => String((index % 5) + 1);
  return (
    <figure data-terp="proportion-bar" aria-labelledby={captionId}>
      <figcaption id={captionId} data-terp="chart-caption">
        {resolve(label)}
      </figcaption>
      <svg
        data-terp="proportion-bar-track"
        viewBox="0 0 100 1"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        {segments.map((segment, index) =>
          segment.width > 0 ? (
            <rect
              key={index}
              data-terp="proportion-bar-part"
              data-tone={parts[index]!.tone}
              data-series={parts[index]!.tone === undefined ? series(index) : undefined}
              x={segment.x}
              y={0}
              width={segment.width}
              height={1}
            />
          ) : null,
        )}
        {segments.slice(1).map((segment, index) =>
          segment.width > 0 && segment.x > 0 ? (
            <line
              key={index}
              data-terp="proportion-bar-gap"
              x1={segment.x}
              x2={segment.x}
              y1={0}
              y2={1}
            />
          ) : null,
        )}
      </svg>
      <ul data-terp="chart-legend">
        {parts.map((part, index) => (
          <li key={index} data-terp="chart-legend-item">
            <span
              data-terp="chart-swatch"
              data-tone={part.tone}
              data-series={part.tone === undefined ? series(index) : undefined}
              aria-hidden="true"
            />
            <span>{resolve(part.label)}</span>
            <span data-terp="chart-legend-value">
              {formatNumber(part.value, format)}
              {total > 0 && ` · ${formatNumber(counted[index]! / total, PERCENT)}`}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
