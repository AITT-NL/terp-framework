import { useLocale } from "../locale";
import { injectTerpStyles } from "../styles";
import type { BadgeTone } from "../ui/Badge";
import { fillPlaceholders, useStrings, useUiText } from "../uiText";
import type { UiText } from "../uiText";

injectTerpStyles();

/**
 * One way a run can end: its word and its tone. Declared once per ending and reused by every
 * run that ends that way -- and an object rather than a string beside a tone, so its word is a
 * `label`, which the i18n lint reads as copy wherever it is written.
 */
export interface StatusOutcome {
  /** The ending in words ("Succeeded", "Timed out"). */
  label: UiText;
  /** Its tone: the cell's colour. */
  tone: BadgeTone;
}

/** One run and how it ended. */
export interface StatusRun {
  /** Which run — its time or its number. */
  label: UiText;
  /** How it ended. */
  outcome: StatusOutcome;
}

export interface StatusHistoryProps {
  /** What ran ("Runs"): the start of the text alternative. */
  label: UiText;
  /** The runs, oldest first. */
  runs: readonly StatusRun[];
}

/**
 * How the recent runs of something ended, one cell per run, oldest first (ADR 0169 §6): a sync's
 * runs, a webhook's deliveries, a check's results.
 *
 * A tone is always also a word: the latest run's ending is printed beside the cells, and every
 * run is read out, its label and its ending, in the order drawn — the cells themselves are
 * hidden from assistive technology. Phrasing content throughout, so it sits in a page's summary
 * band, a collection's cell or a hub card's link alike.
 */
export function StatusHistory({ label, runs }: StatusHistoryProps) {
  const resolve = useUiText();
  const strings = useStrings();
  const locale = useLocale()?.locale;
  const latest = runs.at(-1);
  const text = fillPlaceholders(strings.statusHistoryRuns, {
    label: resolve(label),
    runs: new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(
      runs.map((run) => `${resolve(run.label)}: ${resolve(run.outcome.label)}`),
    ),
  });
  return (
    <span data-terp="status-history">
      <span data-terp="status-history-cells" aria-hidden="true">
        {runs.map((run, index) => (
          <span key={index} data-terp="status-history-cell" data-tone={run.outcome.tone} />
        ))}
      </span>
      {latest !== undefined && (
        <span data-terp="status-history-latest" aria-hidden="true">
          {resolve(latest.outcome.label)}
        </span>
      )}
      <span data-terp="status-history-data">{text}</span>
    </span>
  );
}
