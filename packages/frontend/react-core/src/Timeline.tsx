import type { FormattableDate } from "./format";
import { useFormatDateTime } from "./format";
import { injectTerpStyles } from "./styles";
import type { BadgeTone } from "./ui/Badge";
import { resolveUiTextNode, useUiText } from "./uiText";
import type { UiText, UiTextNode } from "./uiText";

injectTerpStyles();

/** One thing that happened, and when. */
export interface TimelineEvent {
  /** What happened, in words ("Updated", "Approved"). */
  label: UiText;
  /** When: a date-time the `format` helpers take, printed in the app's locale with its time. */
  when: FormattableDate;
  /** One line more — who did it, or what it changed. */
  detail?: UiTextNode;
  /**
   * The event's tone where it marks a change of state worth seeing at a glance — a deletion
   * as danger. The label is its word, so the marker's colour never carries meaning alone.
   */
  tone?: BadgeTone;
}

export interface TimelineProps {
  /** What the events are of ("History"): the list's accessible name. */
  label: UiText;
  /** The events, in the order to read them — a record's history newest first. */
  events: readonly TimelineEvent[];
}

/** An ISO string for `<time dateTime>`, or nothing where the value is not a date. */
function isoOf(value: FormattableDate): string | undefined {
  const date = value instanceof Date ? value : value === null || value === undefined ? null : new Date(value);
  return date === null || Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

/**
 * Events in order (ADR 0169 §5): what happened to a record, and when, on a line that joins them
 * — a record's audit trail on its detail page, a request's steps.
 *
 * An ordered list, so a screen reader announces how many events there are and where it is
 * among them, and each `when` is a `<time>` carrying its machine-readable instant. The marker is
 * decoration: the label says what its tone shows. Unframed, so it reads in a card or on the page
 * alike.
 */
export function Timeline({ label, events }: TimelineProps) {
  const resolve = useUiText();
  const formatDateTime = useFormatDateTime();
  return (
    <ol data-terp="timeline" aria-label={resolve(label)}>
      {events.map((event, index) => (
        <li key={index} data-terp="timeline-event" data-tone={event.tone}>
          <span data-terp="timeline-marker" aria-hidden="true" />
          <span data-terp="timeline-label">{resolve(event.label)}</span>
          <time data-terp="timeline-when" dateTime={isoOf(event.when)}>
            {formatDateTime(event.when)}
          </time>
          {event.detail !== undefined &&
            event.detail !== null &&
            event.detail !== false &&
            event.detail !== "" && (
              <span data-terp="timeline-detail">{resolveUiTextNode(event.detail, resolve)}</span>
            )}
        </li>
      ))}
    </ol>
  );
}
