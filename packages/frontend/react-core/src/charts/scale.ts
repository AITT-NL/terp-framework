/**
 * The arithmetic every chart kind shares: a value axis with round bounds, and positions on a
 * plot whose coordinates are proportions rather than pixels.
 *
 * Kept free of React and of the DOM, so the geometry is tested as numbers — the screenshot lane
 * shows a picture, and a picture cannot say that a column is a pixel too short.
 */

/** The plot's coordinate space. The SVG stretches to its box, so these are proportions. */
export const PLOT_WIDTH = 100;
export const PLOT_HEIGHT = 40;

/** A value axis: its bottom, its top and the tick between them. */
export interface ValueAxis {
  low: number;
  high: number;
  /** The three ticks, top first, the order the labels are read down the axis. */
  ticks: readonly [number, number, number];
}

/** The smallest of 1, 2, 2.5 and 5 times a power of ten that is at least `raw`. */
export function niceStep(raw: number): number {
  if (!(raw > 0) || !Number.isFinite(raw)) {
    return 1;
  }
  const power = 10 ** Math.floor(Math.log10(raw));
  for (const factor of [1, 2, 2.5, 5, 10]) {
    if (factor * power >= raw - power * 1e-9) {
      return factor * power;
    }
  }
  return 10 * power;
}

/**
 * A value axis over `values` in two equal steps of a round size, so its three tick labels can
 * sit at the top, the middle and the bottom of the plot with no position of their own.
 *
 * `fromZero` keeps zero on the axis — required where a mark's length is its value (an area, a
 * column), and left off for a line, where an axis from zero flattens the change the line is
 * there to show. An empty or a flat series still gets an axis with height.
 */
export function valueAxis(values: readonly number[], fromZero: boolean): ValueAxis {
  const finite = values.filter((value) => Number.isFinite(value));
  let min = finite.length === 0 ? 0 : Math.min(...finite);
  let max = finite.length === 0 ? 0 : Math.max(...finite);
  if (fromZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }
  if (min === max) {
    // A flat series: give it a step either side of itself, or one step above zero.
    const pad = niceStep(Math.abs(max) || 1);
    min = fromZero && min >= 0 ? 0 : min - pad;
    max = max + pad;
  }
  let step = niceStep((max - min) / 2);
  for (;;) {
    const low = Math.floor(min / step) * step;
    const high = low + 2 * step;
    if (high >= max - step * 1e-9) {
      return { low: clean(low), high: clean(high), ticks: [clean(high), clean(low + step), clean(low)] };
    }
    step = niceStep(step * 1.01);
  }
}

/** Float residue off a computed tick (0.30000000000000004 is 0.3). */
const clean = (value: number) => Number.parseFloat(value.toPrecision(12));

/** The y coordinate of `value` on an axis, top of the plot highest. */
export function yOf(value: number, axis: ValueAxis): number {
  const share = (value - axis.low) / (axis.high - axis.low);
  return round(PLOT_HEIGHT - share * PLOT_HEIGHT);
}

/** The x coordinate of point `index` of `count`, the first at the left edge and the last at the right. */
export function xOf(index: number, count: number): number {
  return count <= 1 ? PLOT_WIDTH / 2 : round((index / (count - 1)) * PLOT_WIDTH);
}

/** A column's left edge and width, in a band of its own: each of `count` bands holds one column. */
export function columnOf(index: number, count: number): { x: number; width: number } {
  const band = PLOT_WIDTH / count;
  const width = band * 0.6;
  return { x: round(index * band + (band - width) / 2), width: round(width) };
}

export const round = (value: number) => Math.round(value * 100) / 100;
