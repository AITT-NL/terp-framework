import { useFormatNumber } from "./format";
import { injectTerpStyles } from "./styles";
import { useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

/**
 * Which part of its range a banded meter's value sits in, in the HTML standard's own words.
 *
 * `optimum` is where the caller said good values lie, `suboptimum` is next to it, and
 * `even-less-good` is the far side — the words the standard uses for the three regions that
 * `low`, `high` and `optimum` define, and the words WebKit and Blink name their value
 * pseudo-elements after.
 */
type MeterRegion = "optimum" | "suboptimum" | "even-less-good";

export interface MeterProps {
  /**
   * The measured value.
   *
   * Drawn clamped to the range, as the element itself draws it, and printed as it is: a quota
   * overrun prints `120%` against a full bar, because the text is where a reader learns the
   * bar has run out of room.
   */
  value: number;
  /** The bottom of the range (default `0`). */
  min?: number;
  /** The top of the range (default `1`, the element's own default — so a bare value is a fraction). */
  max?: number;
  /** The top of the low band. Declaring any band colours the bar by the region its value falls in. */
  low?: number;
  /** The bottom of the high band. */
  high?: number;
  /** Where the good values lie: below `low`, above `high`, or between them. */
  optimum?: number;
  /**
   * The meter's accessible name. Required — an unnamed meter is announced as a number with
   * nothing to say what it measures.
   *
   * It is not printed. Every place a quantity sits already carries a visible caption of its own
   * — a `DetailList` term, a `Card` title, a `HubCard` title — and printing the label as well
   * puts the same word twice on one line. Name the meter with the words that caption uses.
   */
  label: UiText;
  /**
   * How the printed value is formatted, as the `Intl.NumberFormatOptions` the `format`
   * helpers take (default: a percentage).
   *
   * A percentage is always the value's **share of the range**, so `value={74} max={100}`
   * prints `74%` where the bare Intl option would print `7,400%`. Every other style prints the
   * value itself: `{ style: "unit", unit: "gigabyte" }` for a quota, `{}` for a plain score.
   * The locale is the app's, never the browser's.
   */
  format?: Intl.NumberFormatOptions;
}

/** The default format, hoisted so the formatter cache sees one options object rather than one per render. */
const PERCENT: Intl.NumberFormatOptions = { style: "percent" };

const clamp = (value: number, floor: number, ceiling: number) =>
  Math.min(Math.max(value, floor), ceiling);

/**
 * The region a banded value sits in — the HTML standard's gauge-region algorithm, written out.
 *
 * Written out rather than read from the browser, because the browser does not say: the element
 * has no DOM property for its region, and a stylesheet can only see it through a
 * different vendor hook per engine, so a rule keyed on the attribute this returns is the one
 * way a single sheet can colour every engine alike. The boundaries are inclusive exactly where
 * Chromium's are: measured against the region Chromium itself paints, for every shape the
 * standard distinguishes — an optimum below, between and above the bands, each boundary
 * value, bands outside the range, a `high` below `low` on either side of the optimum, a range
 * that is not 0 to 1 — with no disagreement. `Meter.test.tsx` holds this function to cases
 * taken from that measurement.
 */
function meterRegion({
  value,
  min = 0,
  max = 1,
  low,
  high,
  optimum,
}: Pick<MeterProps, "value" | "min" | "max" | "low" | "high" | "optimum">): MeterRegion {
  // The standard's clamping, in its own order: a max below the min becomes the min, the value
  // and each boundary are pulled inside the range, and a high below the low becomes the low.
  const top = Math.max(max, min);
  const at = clamp(value, min, top);
  const lowEdge = clamp(low ?? min, min, top);
  const highEdge = clamp(high ?? top, lowEdge, top);
  const best = clamp(optimum ?? (min + top) / 2, min, top);
  if (best < lowEdge) {
    return at <= lowEdge ? "optimum" : at <= highEdge ? "suboptimum" : "even-less-good";
  }
  if (best > highEdge) {
    return at >= highEdge ? "optimum" : at >= lowEdge ? "suboptimum" : "even-less-good";
  }
  return at >= lowEdge && at <= highEdge ? "optimum" : "suboptimum";
}

/**
 * One bounded value — a quota used, a score against its range — as a bar with the value
 * printed beside it.
 *
 * The bar IS the native `<meter>`, styled from the sheet: the element carries its own
 * semantics, the browser draws the proportion from its attributes, and so there is no inline
 * width and no second element pretending to be the first. Its fill is `--color-fg-accent` on a
 * `--color-bg-inset` track — the accent that is ink on the app's own surfaces, not the brand
 * fill, which falls under 3:1 against the track in all three dark themes.
 *
 * **Bands are opt-in.** With none declared the bar is one colour, because "a value in its range"
 * is not a judgement. Declare `low`, `high` or `optimum` and the fill takes the region's tone —
 * success, warning, danger. The colour reinforces the printed value and never replaces it: if
 * the judgement itself matters, say it in words beside the meter (a `Badge`), because the
 * region is not in the accessibility tree — measured in Chromium, whose tree carries the
 * value and the range and nothing about the bands.
 *
 * **One accessible element.** The printed value is `aria-hidden` and handed to the meter as its
 * `aria-valuetext`, so a screen reader hears the same `62%` a sighted reader sees, once — and a
 * meter inside a `HubCard` stat adds that text to the card link's name rather than the raw
 * `0.62`. Measured in Chromium: with the printed value left in the tree the link read its value
 * twice.
 *
 * ```tsx
 * <DetailList items={[{ label: storage, value: <Meter label={storage} value={used} max={quota} /> }]} />
 * ```
 */
export function Meter({ value, min = 0, max = 1, low, high, optimum, label, format }: MeterProps) {
  const resolve = useUiText();
  const formatNumber = useFormatNumber();
  const options = format ?? PERCENT;
  const top = Math.max(max, min);
  // A range with no width has no share, and the browser paints no fill for it (measured):
  // NaN prints the framework's dash, where the division would print an infinity.
  const share = top > min ? (value - min) / (top - min) : Number.NaN;
  const text = formatNumber(options.style === "percent" ? share : value, options);
  const banded = low !== undefined || high !== undefined || optimum !== undefined;
  return (
    <span data-terp="meter">
      <meter
        data-terp="meter-bar"
        data-region={
          banded ? meterRegion({ value, min, max, low, high, optimum }) : undefined
        }
        value={value}
        min={min}
        max={max}
        low={low}
        high={high}
        optimum={optimum}
        aria-label={resolve(label)}
        aria-valuetext={text}
      />
      <span data-terp="meter-value" aria-hidden="true">
        {text}
      </span>
    </span>
  );
}
