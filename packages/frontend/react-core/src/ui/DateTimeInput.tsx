import { useState } from "react";
import type { InputHTMLAttributes } from "react";

import { injectTerpStyles } from "../styles";

injectTerpStyles();

type NativeProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "defaultValue" | "onChange" | "min" | "max"
>;

export interface DateTimeInputProps extends NativeProps {
  /**
   * The instant shown, as the API sends one: an RFC 3339 date and time with its UTC offset
   * (`2026-11-06T09:00:00Z`), or `null` for none. A value without an offset names no instant,
   * so it is shown as empty rather than guessed at.
   */
  value?: string | null;
  /** The instant shown first, uncontrolled. */
  defaultValue?: string | null;
  /**
   * The instant picked, as an RFC 3339 date and time with the zone's offset
   * (`2026-11-06T10:00:00+01:00`), ready to send; `null` once the field is cleared.
   */
  onChange?: (value: string | null) => void;
  /**
   * The IANA time zone the time is shown and read in (`Europe/Amsterdam`); the browser's own
   * when absent. When it is not the person's own zone, say which it is in the field's hint.
   */
  zone?: string;
  /** The earliest instant that may be picked, as `value` takes one. */
  min?: string;
  /** The latest instant that may be picked, as `value` takes one. */
  max?: string;
}

/**
 * A date and time a person picks, sent as the instant it names (ADR 0206).
 *
 * A `datetime-local` input's own value is a wall time with no UTC offset, which names no
 * instant, and the server refuses one. This shows the instant as a wall time in a zone and
 * sends what the person picks back as an instant with that zone's offset. A wall time the
 * clocks skip moves forward past the gap, and one they repeat is the earlier of the two, the
 * choice JavaScript's own dates and Temporal make. The control is the browser's, so it is
 * localised by the browser, and the `data-terp="input"` marker styles it like every input.
 */
export function DateTimeInput({
  value,
  defaultValue = null,
  onChange,
  zone,
  min,
  max,
  ...rest
}: DateTimeInputProps) {
  const timeZone = zone ?? browserZone();
  const [uncontrolled, setUncontrolled] = useState<string | null>(defaultValue);
  const shown = value === undefined ? uncontrolled : value;

  return (
    <input
      {...rest}
      data-terp="input"
      type="datetime-local"
      value={wallTime(shown, timeZone)}
      min={min === undefined ? undefined : wallTime(min, timeZone) || undefined}
      max={max === undefined ? undefined : wallTime(max, timeZone) || undefined}
      onChange={(event) => {
        const next = instantOf(event.target.value, timeZone);
        if (value === undefined) {
          setUncontrolled(next);
        }
        onChange?.(next);
      }}
    />
  );
}

/** The zone the browser runs in, which is the person's own unless they set it otherwise. */
function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";
}

const MINUTE = 60_000;
const DAY = 86_400_000;
const WITH_OFFSET = /(?:Z|[+-]\d{2}:\d{2})$/i;
const WALL_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/;

const formatters = new Map<string, Intl.DateTimeFormat>();

interface Fields {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

/** The calendar date and wall time *instant* reads as in *zone*. */
function fieldsIn(instant: number, zone: string): Fields {
  let formatter = formatters.get(zone);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(zone, formatter);
  }
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(instant)).map((part) => [part.type, part.value]),
  );
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
  };
}

/** How many minutes *zone* runs ahead of UTC at *instant*. */
function offsetMinutes(instant: number, zone: string): number {
  const fields = fieldsIn(instant, zone);
  const asUtc = Date.UTC(fields.year, fields.month - 1, fields.day, fields.hour, fields.minute, fields.second);
  return Math.round((asUtc - Math.floor(instant / 1000) * 1000) / MINUTE);
}

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

/** The wall time an instant reads as in *zone*, as a `datetime-local` input takes it. */
function wallTime(value: string | null, zone: string): string {
  if (value === null || !WITH_OFFSET.test(value)) {
    return "";
  }
  const instant = Date.parse(value);
  if (Number.isNaN(instant)) {
    return "";
  }
  const fields = fieldsIn(instant, zone);
  return `${pad(fields.year, 4)}-${pad(fields.month)}-${pad(fields.day)}T${pad(fields.hour)}:${pad(fields.minute)}`;
}

/** The instant a wall time names in *zone*, with that zone's offset; `null` for none. */
function instantOf(wall: string, zone: string): string | null {
  const match = WALL_TIME.exec(wall);
  if (match === null) {
    return null;
  }
  const [, year, month, day, hour, minute, second] = match;
  const local = Date.UTC(+year, +month - 1, +day, +hour, +minute, second === undefined ? 0 : +second);
  // The offsets on either side of any change of the clocks near this wall time; each is a
  // candidate, and it names this wall time if the zone runs at that offset at that instant.
  const before = offsetMinutes(local - DAY, zone);
  const after = offsetMinutes(local + DAY, zone);
  const fits = [before, after]
    .map((offset) => local - offset * MINUTE)
    .filter((candidate) => offsetMinutes(candidate, zone) * MINUTE === local - candidate);
  // Repeated, both fit and the earlier is taken; skipped, none fits and the offset before the
  // gap carries the wall time past it.
  const instant = fits.length > 0 ? Math.min(...fits) : local - before * MINUTE;
  return rfc3339(instant, zone);
}

/** *instant* as an RFC 3339 date and time in *zone*, with the zone's offset at that instant. */
function rfc3339(instant: number, zone: string): string {
  const fields = fieldsIn(instant, zone);
  const offset = offsetMinutes(instant, zone);
  const magnitude = Math.abs(offset);
  const suffix =
    offset === 0
      ? "Z"
      : `${offset < 0 ? "-" : "+"}${pad(Math.floor(magnitude / 60))}:${pad(magnitude % 60)}`;
  return (
    `${pad(fields.year, 4)}-${pad(fields.month)}-${pad(fields.day)}` +
    `T${pad(fields.hour)}:${pad(fields.minute)}:${pad(fields.second)}${suffix}`
  );
}
