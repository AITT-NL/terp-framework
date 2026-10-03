import { useContext, useEffect } from "react";
import type { ReactNode } from "react";

import { formatList, useFormatNumber } from "./format";
import { HeadlineContext } from "./layoutContract";
import { useLocale } from "./locale";
import { Meter } from "./Meter";
import type { MeterProps } from "./Meter";
import { injectTerpStyles } from "./styles";
import { fillPlaceholders, resolveUiTextNode, useStrings, useUiText } from "./uiText";
import type { UiText, UiTextNode } from "./uiText";

injectTerpStyles();

/**
 * Whether a change is good news, bad news, or neither.
 *
 * The caller's fact, never inferred (ADR 0169 §5): more rows synced is good and more deliveries
 * failed is bad, and only the module that owns the number knows which — the reason ADR 0097 §5
 * gave for refusing a navigation badge a tone of its own.
 */
export type StatSentiment = "positive" | "negative" | "neutral";

/** A figure's change against an earlier value of itself. */
export interface StatDelta {
  /** The change. Its sign is the arrow's direction, and zero reads as unchanged. */
  value: number;
  /** Whether the change is good news, bad news or neither — see {@link StatSentiment}. */
  sentiment: StatSentiment;
  /**
   * How the change prints, as the `Intl.NumberFormatOptions` the `format` helpers take
   * (default: a plain number). It always carries its sign, so `{ style: "percent" }` with
   * `0.12` prints `+12%`; a `signDisplay` of the caller's own is overridden to keep it.
   *
   * The printed change is what the arrow and the tone follow: a change that rounds to zero in
   * this format prints `0`, draws the bar for no change and reads as neutral, whatever its
   * declared sentiment, because there is no change left to judge.
   */
  format?: Intl.NumberFormatOptions;
  /**
   * What the change is measured against — "vs last week", "since the previous run". `label`
   * rather than a name of its own, so the i18n lint reads it as copy wherever it is written.
   */
  label?: UiText;
}

/** One point of a figure's recent history: when, and how much. */
export interface StatPoint {
  /** When — a period's name or a formatted date. Read out in the trend's text alternative. */
  label: UiText;
  /** How much, in the figure's own format. */
  value: number;
}

/** The range a figure is read against: `Meter`'s range and bands, with the top required. */
export type StatTarget = Omit<MeterProps, "value" | "label" | "max"> & {
  /** The top of the range — the budget, the quota, the goal. */
  max: number;
};

export interface StatProps {
  /** What the figure is ("Open orders"). Printed above the value, and the target meter's name. */
  label: UiText;
  /**
   * The figure. A number prints through the `format` helpers in the app's locale; a string
   * prints as written, for a figure that is not a quantity ("3 d 4 h", "A+"); `null` or
   * `undefined` prints the framework's dash, for a figure not known yet.
   */
  value: number | string | null | undefined;
  /** How a numeric value prints, as `Intl.NumberFormatOptions` (default: a plain number). */
  format?: Intl.NumberFormatOptions;
  /** The change against an earlier value, as a pill whose tone is the declared sentiment. */
  delta?: StatDelta;
  /**
   * The figure's recent history, oldest first, drawn as a sparkline under the value — ADR
   * 0158's sparkline, the first chart kind. Two points or more draw a line; every point is
   * also read out as text, which is the sparkline's data alternative.
   */
  trend?: readonly StatPoint[];
  /**
   * The range the figure is read against, drawn as a `Meter` under the value: a spend against
   * its budget, a count against the minimum it must reach. Declare `low`, `high` and
   * `optimum` for the bands, as on `Meter`. Ignored unless the value is a number.
   */
  target?: StatTarget;
  /** One short line under the figure — "of 1,200 budgeted", "last run 4 minutes ago". */
  caption?: UiTextNode;
  /**
   * The page's headline figure: filled with the brand colour, the loudest thing on the page.
   *
   * At most one figure on a page is the headline — scarcity is what lets the accent mean
   * something (ADR 0169 §4) — and under a layout contract both halves refuse a second one.
   */
  headline?: boolean;
}

const DASH = "—";

/** The delta's sign rule, applied last over the caller's format so the sign always shows. */
const SIGNED: Intl.NumberFormatOptions = { signDisplay: "exceptZero" };

// The arrow, as geometry: a triangle up, one down, and a bar for no change. Paths rather than
// glyphs, so the mark is the same in every font and its colour is the pill's.
const ARROWS = {
  up: "M6 2 L11 10 L1 10 Z",
  down: "M6 10 L1 2 L11 2 Z",
  flat: "M1 5 H11 V7 H1 Z",
} as const;

// The sparkline's canvas. The SVG is stretched to its box (preserveAspectRatio="none"), so these
// are proportions rather than pixels; the stroke keeps its width through the stretch because
// the sheet gives it vector-effect: non-scaling-stroke.
const TREND_WIDTH = 100;
const TREND_HEIGHT = 24;
const TREND_INSET = 2;

/**
 * Which way a change points, read from the change as it prints rather than as it was passed:
 * `0.004` as a percentage prints `0%`, and an up arrow beside `0%` would contradict itself.
 * The sign is a part of its own in `formatToParts`, so this holds in every locale's spelling.
 */
function directionOf(
  value: number,
  format: Intl.NumberFormatOptions,
  locale: string | undefined,
): "up" | "down" | "flat" {
  const parts = new Intl.NumberFormat(locale, format).formatToParts(value);
  return parts.some((part) => part.type === "plusSign")
    ? "up"
    : parts.some((part) => part.type === "minusSign")
      ? "down"
      : "flat";
}

/** The sparkline's points, scaled to its canvas: x by position, y by value, top is highest. */
function trendPoints(values: readonly number[]): string {
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low;
  const step = TREND_WIDTH / (values.length - 1);
  return values
    .map((value, index) => {
      // A flat series is a line through the middle, not a line along the floor.
      const share = span === 0 ? 0.5 : (value - low) / span;
      const y = TREND_HEIGHT - TREND_INSET - share * (TREND_HEIGHT - 2 * TREND_INSET);
      return `${round(index * step)},${round(y)}`;
    })
    .join(" ");
}

const round = (value: number) => Math.round(value * 100) / 100;

/**
 * One figure, with what it needs to be read: its label, its value in the app's locale, how it
 * changed, its recent history, and the range it sits in.
 *
 * The shape of data ADR 0169 calls "one figure, with context". A `Card` with a title and a line
 * of text was the way to show one, and it put the label above the number in a larger type than
 * the number — the figure was the quietest thing in its own box. Here the value is the largest
 * type on the tile, and the label names it.
 *
 * **Where it sits.** On its own, a figure is a tile on `--color-bg-surface`, the rung where data
 * is read (ADR 0169 §3). Several figures about one subject are a {@link StatGroup}, which draws
 * them as one ruled row without a tile each. In a `HubCard`'s `stat` row the card is the frame,
 * so the figure has none of its own. The `headline` figure is filled with the brand colour.
 *
 * **A tone is also a word.** The delta's pill is coloured by the declared sentiment and carries
 * its sign, so every reader sees the direction; the sentiment itself is a word in the
 * accessibility tree ("favourable", "unfavourable"), because a colour alone says it to nobody
 * who cannot see the colour. The sparkline is drawn for the eye and read out as text — each
 * point's label and value — which is ADR 0158's data alternative in the one form valid inside a
 * `HubCard`'s link: a figure is phrasing content throughout, so a table cannot be.
 *
 * It renders no inline styles: the sparkline is SVG geometry in attributes, and every colour
 * comes from the sheet, keyed on the markers and on `data-sentiment` (ADR 0094, ADR 0169 §7).
 *
 * ```tsx
 * <Stat
 *   label={{ id: "orders.open", message: "Open orders" }}
 *   value={1284}
 *   delta={{ value: 0.12, format: { style: "percent" }, sentiment: "positive", label: { id: "orders.vsLastWeek", message: "vs last week" } }}
 *   trend={weeks.map((week) => ({ label: week.name, value: week.open }))}
 * />
 * ```
 */
export function Stat({
  label,
  value,
  format,
  delta,
  trend,
  target,
  caption,
  headline = false,
}: StatProps) {
  const resolve = useUiText();
  const strings = useStrings();
  const formatNumber = useFormatNumber();
  const locale = useLocale()?.locale;
  // A headline registers with its page, which counts them (ADR 0169 §4): a figure that
  // renders late -- after its own data arrives -- is counted when it arrives, where a DOM count
  // taken when the page rendered would have missed it.
  const headlines = useContext(HeadlineContext);
  useEffect(
    () => (headline && headlines !== null ? headlines.register() : undefined),
    [headline, headlines],
  );
  const printed =
    typeof value === "number"
      ? formatNumber(value, format)
      : typeof value === "string" && value !== ""
        ? value
        : DASH;
  const deltaFormat =
    delta === undefined ? SIGNED : { ...(delta.format ?? {}), ...SIGNED };
  const direction =
    delta === undefined || !Number.isFinite(delta.value)
      ? undefined
      : directionOf(delta.value, deltaFormat, locale);
  // No change left to judge is neutral, whatever was declared for the change.
  const sentiment = direction === "flat" ? "neutral" : delta?.sentiment;
  const sentimentWord =
    sentiment === "positive"
      ? strings.statFavourable
      : sentiment === "negative"
        ? strings.statUnfavourable
        : undefined;
  const points = trend ?? [];
  // The text alternative names every point, label and value, in the order drawn and joined the
  // way the app's locale joins a list ("a, b and c"), so it reads as a sentence in every
  // language. A value that is not a number prints the dash here and draws nothing below.
  const trendText =
    points.length === 0
      ? undefined
      : fillPlaceholders(strings.statTrend, {
          points: formatList(
            points.map((point) => `${resolve(point.label)}: ${formatNumber(point.value, format)}`),
            locale,
          ),
        });
  const drawable = points.map((point) => point.value).filter((value) => Number.isFinite(value));
  const line = drawable.length >= 2 ? trendPoints(drawable) : undefined;
  const showsTarget = target !== undefined && typeof value === "number" && Number.isFinite(value);
  return (
    <span data-terp="stat" data-headline={headline ? "true" : undefined}>
      <span data-terp="stat-label">{resolve(label)}</span>
      <span data-terp="stat-value">{printed}</span>
      {delta !== undefined && direction !== undefined && (
        <span data-terp="stat-delta">
          <span data-terp="stat-change" data-sentiment={sentiment}>
            <svg data-terp="stat-arrow" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
              <path d={ARROWS[direction]} />
            </svg>
            {formatNumber(delta.value, deltaFormat)}
            {sentimentWord !== undefined && (
              <span data-terp="stat-sentiment">{` ${sentimentWord}`}</span>
            )}
          </span>
          {delta.label !== undefined && (
            <span data-terp="stat-delta-label">{resolve(delta.label)}</span>
          )}
        </span>
      )}
      {/* The series' text, alone when there is no line to draw: as the only child of a block
          of its own it left an empty block the height of the block's margin. */}
      {trendText !== undefined && line === undefined && (
        <span data-terp="stat-trend-data">{trendText}</span>
      )}
      {trendText !== undefined && line !== undefined && (
        <span data-terp="stat-trend">
          <svg
            data-terp="stat-trend-chart"
            viewBox={`0 0 ${TREND_WIDTH} ${TREND_HEIGHT}`}
            preserveAspectRatio="none"
            aria-hidden="true"
            focusable="false"
          >
            <polygon
              data-terp="stat-trend-area"
              points={`0,${TREND_HEIGHT} ${line} ${TREND_WIDTH},${TREND_HEIGHT}`}
            />
            <polyline data-terp="stat-trend-line" points={line} />
          </svg>
          <span data-terp="stat-trend-data">{trendText}</span>
        </span>
      )}
      {showsTarget && <Meter label={label} value={value} {...target} />}
      {caption !== undefined && caption !== null && caption !== false && caption !== "" && (
        <span data-terp="stat-caption">{resolveUiTextNode(caption, resolve)}</span>
      )}
    </span>
  );
}

export interface StatGroupProps {
  /** The figures: `Stat`s, one of which may be the page's headline. */
  children: ReactNode;
}

/**
 * Several figures about one subject, as one ruled row: the shape ADR 0169 calls "a group of
 * figures", and the usual content of a page's `summary` band.
 *
 * Unframed, always — the figures sit on whatever the group sits on, divided by hairline rules
 * rather than boxed one by one, so a row of four figures reads as one statement about the
 * subject rather than four tiles. It is the same row in the summary band and in a body; nothing
 * about it changes with where it is placed.
 *
 * The row wraps by itself, as many figures to a line as fit at 8rem (two on a phone), and a
 * figure that starts a line carries no rule before it.
 */
export function StatGroup({ children }: StatGroupProps) {
  return <span data-terp="stat-group">{children}</span>;
}
