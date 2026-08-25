import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { formatDate } from "../format";
import { useLocale } from "../locale";
import { injectTerpStyles } from "../styles";
import { useStrings, useUiText } from "../uiText";
import type { UiText } from "../uiText";
import { Popover } from "./Popover";

injectTerpStyles();

export interface DateRangeValue {
  start: Date | null;
  end: Date | null;
}

export interface DatePickerProps {
  value?: Date | null;
  defaultValue?: Date | null;
  onChange?: (value: Date | null) => void;
  min?: Date;
  max?: Date;
  disabled?: boolean;
  placeholder?: UiText;
  "aria-label"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  /** Open the calendar on mount (uncontrolled), the same shape `Popover` and `Menu` take. */
  defaultOpen?: boolean;
}

export interface DateRangePickerProps {
  value?: DateRangeValue;
  defaultValue?: DateRangeValue;
  onChange?: (value: DateRangeValue) => void;
  min?: Date;
  max?: Date;
  disabled?: boolean;
  placeholder?: UiText;
  "aria-label"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  /** Open the calendar on mount (uncontrolled), the same shape `Popover` and `Menu` take. */
  defaultOpen?: boolean;
}

/** Single-date calendar picker with locale-aware labels and keyboard navigation. */
export function DatePicker({
  value,
  defaultValue = null,
  onChange,
  min,
  max,
  disabled = false,
  placeholder,
  "aria-label": ariaLabel,
  "aria-invalid": ariaInvalid,
  defaultOpen = false,
}: DatePickerProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState<Date | null>(defaultValue);
  const selected = normalizeDate(value ?? uncontrolledValue);
  // `&& !disabled` is not belt-and-braces. Every close path runs through
  // onOpenChange, which swallows the change while disabled — so a disabled picker seeded
  // open would render a calendar that Escape, an outside click and its own onEscape all
  // fail to dismiss, and whose day clicks still fire onChange from a control the app
  // marked disabled. Only reachable since defaultOpen existed: before it, the sole way in
  // was clicking the disabled trigger.
  const [open, setOpen] = useState(defaultOpen && !disabled);
  const locale = useDateLocale();
  const strings = useStrings();
  const resolve = useUiText();
  // Falls back to the string TABLE rather than to a literal default on the prop. A
  // `placeholder = "Select date"` default is overridable and still untranslatable: a plain
  // string resolves as-is, so an app that does not pass the prop shows English in every
  // locale. Reaching the table means the app's own catalogue answers when the caller says
  // nothing, which is the whole point of having one.
  const formatted =
    selected === null ? resolve(placeholder ?? strings.selectDate) : formatDate(selected, locale);

  function commit(next: Date) {
    if (value === undefined) {
      setUncontrolledValue(next);
    }
    onChange?.(next);
    setOpen(false);
  }

  return (
    <Popover
      open={open && !disabled}
      onOpenChange={(next) => !disabled && setOpen(next)}
      align="start"
      trigger={
        <button
          type="button"
          data-terp="input"
          aria-haspopup="dialog"
          aria-label={ariaLabel}
          aria-invalid={ariaInvalid}
          disabled={disabled}
          data-placeholder={selected === null ? "true" : undefined}
        >
          <span>{formatted}</span>
          <span aria-hidden="true">📅</span>
        </button>
      }
    >
      {({ close }) => (
        <Calendar
          mode="single"
          locale={locale}
          selected={selected}
          visibleSeed={selected ?? new Date()}
          min={min}
          max={max}
          onSelect={commit}
          onEscape={() => close(true)}
        />
      )}
    </Popover>
  );
}

/** Range calendar picker with start/end selection, min/max bounds and locale-aware labels. */
export function DateRangePicker({
  value,
  defaultValue = { start: null, end: null },
  onChange,
  min,
  max,
  disabled = false,
  placeholder,
  "aria-label": ariaLabel,
  "aria-invalid": ariaInvalid,
  defaultOpen = false,
}: DateRangePickerProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState<DateRangeValue>(defaultValue);
  const selected = normalizeRange(value ?? uncontrolledValue);
  // `&& !disabled` is not belt-and-braces. Every close path runs through
  // onOpenChange, which swallows the change while disabled — so a disabled picker seeded
  // open would render a calendar that Escape, an outside click and its own onEscape all
  // fail to dismiss, and whose day clicks still fire onChange from a control the app
  // marked disabled. Only reachable since defaultOpen existed: before it, the sole way in
  // was clicking the disabled trigger.
  const [open, setOpen] = useState(defaultOpen && !disabled);
  const locale = useDateLocale();
  const strings = useStrings();
  const resolve = useUiText();
  const formatted = selected.start === null
    ? resolve(placeholder ?? strings.selectDateRange)
    : selected.end === null
      ? `${formatDate(selected.start, locale)} –`
      : `${formatDate(selected.start, locale)} – ${formatDate(selected.end, locale)}`;

  function commit(next: DateRangeValue) {
    if (value === undefined) {
      setUncontrolledValue(next);
    }
    onChange?.(next);
    if (next.start !== null && next.end !== null) {
      setOpen(false);
    }
  }

  return (
    <Popover
      open={open && !disabled}
      onOpenChange={(next) => !disabled && setOpen(next)}
      align="start"
      trigger={
        <button
          type="button"
          data-terp="input"
          aria-haspopup="dialog"
          aria-label={ariaLabel}
          aria-invalid={ariaInvalid}
          disabled={disabled}
          data-placeholder={selected.start === null ? "true" : undefined}
        >
          <span>{formatted}</span>
          <span aria-hidden="true">📅</span>
        </button>
      }
    >
      {({ close }) => (
        <Calendar
          mode="range"
          locale={locale}
          range={selected}
          visibleSeed={selected.start ?? new Date()}
          min={min}
          max={max}
          onRangeSelect={commit}
          onEscape={() => close(true)}
        />
      )}
    </Popover>
  );
}

interface CalendarProps {
  mode: "single" | "range";
  locale: string | undefined;
  visibleSeed: Date;
  selected?: Date | null;
  range?: DateRangeValue;
  min?: Date;
  max?: Date;
  onSelect?: (date: Date) => void;
  onRangeSelect?: (range: DateRangeValue) => void;
  onEscape: () => void;
}

function Calendar({ mode, locale, visibleSeed, selected = null, range, min, max, onSelect, onRangeSelect, onEscape }: CalendarProps) {
  const strings = useStrings();
  const gridId = useId();
  const titleId = useId();
  const minDate = normalizeDate(min);
  const maxDate = normalizeDate(max);
  const initial = clampDate(normalizeDate(visibleSeed) ?? today(), minDate, maxDate);
  const [month, setMonth] = useState(() => startOfMonth(initial));
  const [activeDate, setActiveDate] = useState(initial);
  const activeRef = useRef<HTMLButtonElement>(null);
  const follow = useRef(false);
  const weeks = useMemo(() => monthWeeks(month), [month]);
  const weekdays = useMemo(() => weekdayNames(locale), [locale]);
  const activeKey = toKey(activeDate);

  // Opening: focus the cursor once the portalled panel exists where it will finally sit
  // (Popover positions it in a layout effect, hence the tick). Its own effect with its own
  // cleanup, deliberately — folding it into the cursor effect below and gating it on a
  // did-mount ref meant StrictMode's mount / cleanup / mount cycle cleared the first timer
  // and then took the other branch, so in development the calendar opened with focus outside
  // the grid and the arrow keys inert.
  useEffect(() => {
    const timer = window.setTimeout(() => activeRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  // The roving cursor has to move DOM focus, not just `tabIndex` — an arrow key used to move
  // `tabIndex={0}` and `activeRef` to another cell while the browser's focus, the focus ring
  // and every screen reader stayed on the day the calendar opened on.
  //
  // The intent is recorded at the EVENT rather than inferred afterwards, and that is the whole
  // correctness argument. Reading `document.activeElement` after the commit looks equivalent
  // and is not: a move across a month boundary re-keys the week rows, so the row holding the
  // focused cell is unmounted, which moves focus to <body> — and a post-commit check then sees
  // focus outside the grid and declines to follow. Measured in a browser: arrowing from
  // 29 January to 5 February left `document.activeElement` on BODY and the calendar
  // keyboard-dead, because the grid's handler is the only key listener. The flag cannot be
  // fooled that way, because only the grid's own handler sets it.
  useEffect(() => {
    if (!follow.current) {
      return;
    }
    follow.current = false;
    activeRef.current?.focus();
  }, [activeKey]);

  /** Move the cursor from a key the grid handled, and take focus with it. */
  function moveCursor(daysDelta: number) {
    follow.current = true;
    move(daysDelta);
  }

  /** Page the month from a key the grid handled. The header buttons deliberately do not. */
  function pageMonth(delta: number) {
    follow.current = true;
    changeMonth(delta);
  }

  function move(daysDelta: number) {
    const next = clampDate(addDays(activeDate, daysDelta), minDate, maxDate);
    setActiveDate(next);
    if (next.getMonth() !== month.getMonth() || next.getFullYear() !== month.getFullYear()) {
      setMonth(startOfMonth(next));
    }
  }

  function changeMonth(delta: number) {
    const nextMonth = addMonths(month, delta);
    setMonth(nextMonth);
    setActiveDate(clampDate(new Date(nextMonth.getFullYear(), nextMonth.getMonth(), Math.min(activeDate.getDate(), daysInMonth(nextMonth))), minDate, maxDate));
  }

  function selectDate(day: Date) {
    if (isDisabled(day, minDate, maxDate)) {
      return;
    }
    if (mode === "single") {
      onSelect?.(day);
      return;
    }
    const current = range ?? { start: null, end: null };
    if (current.start === null || current.end !== null || compareDate(day, current.start) < 0) {
      onRangeSelect?.({ start: day, end: null });
    } else {
      onRangeSelect?.({ start: current.start, end: day });
    }
  }

  function onGridKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "Escape":
        event.preventDefault();
        onEscape();
        break;
      case "ArrowRight":
        event.preventDefault();
        moveCursor(1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        moveCursor(-1);
        break;
      case "ArrowDown":
        event.preventDefault();
        moveCursor(7);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveCursor(-7);
        break;
      case "Home":
        event.preventDefault();
        moveCursor(-activeDate.getDay());
        break;
      case "End":
        event.preventDefault();
        moveCursor(6 - activeDate.getDay());
        break;
      case "PageUp":
        event.preventDefault();
        pageMonth(-1);
        break;
      case "PageDown":
        event.preventDefault();
        pageMonth(1);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        selectDate(activeDate);
        break;
      default:
        break;
    }
  }

  return (
    // Named by its month heading. role="dialog" with no accessible name announces itself as
    // just "dialog", and the month was one level down on the grid — reached only after the
    // dialog boundary had already been crossed unnamed. axe does not report this at the
    // wcag2a/aa tags the lane runs, so opening the calendar in stage 4 did not surface it.
    <div role="dialog" aria-modal="false" aria-labelledby={titleId} data-terp="calendar">
      <div data-terp="calendar-header">
        <button type="button" data-terp="iconbutton" aria-label={strings.previousMonth} onClick={() => changeMonth(-1)}>‹</button>
        <div id={titleId} data-terp="calendar-title">{formatMonth(month, locale)}</div>
        <button type="button" data-terp="iconbutton" aria-label={strings.nextMonth} onClick={() => changeMonth(1)}>›</button>
      </div>
      <div data-terp="calendar-week" aria-hidden="true">
        {weekdays.map((day) => <div key={day} data-terp="calendar-weekday">{day}</div>)}
      </div>
      {/* grid → row → gridcell. The 42 day buttons used to be DIRECT children of the
          role="grid", which is an invalid ARIA grid: `grid` must own `row`s and a
          `gridcell` must be owned by one, so axe rated it a critical violation on two
          rules at once and no screen reader could report "week 3, Wednesday". Nothing
          caught it because nothing in the repo opened a calendar — the resting-state
          baselines have no picture of it and axe never reached the subtree.

          The geometry is unchanged and that is why the rows can be real elements rather
          than `display: contents`: the outer box keeps the row gap, each row keeps the
          seven equal columns and the column gap, and both gaps are the same token they
          always were, so 42 cells land on exactly the pixels they did as one flat grid. */}
      <div
        id={gridId}
        role="grid"
        aria-label={formatMonth(month, locale)}
        data-terp="calendar-grid"
        onKeyDown={onGridKeyDown}
      >
        {weeks.map((week) => (
          <div key={toKey(week[0]!)} role="row" data-terp="calendar-week">
            {week.map((day) => {
              const disabled = isDisabled(day, minDate, maxDate);
              const isSelected = mode === "single"
                ? sameDate(day, selected)
                : sameDate(day, range?.start) || sameDate(day, range?.end);
              const inRange = mode === "range" && isWithinRange(day, range);
              const active = sameDate(day, activeDate);
              return (
                <button
                  key={toKey(day)}
                  ref={active ? activeRef : undefined}
                  type="button"
                  role="gridcell"
                  aria-selected={isSelected}
                  aria-disabled={disabled}
                  tabIndex={active ? 0 : -1}
                  disabled={disabled}
                  onClick={() => selectDate(day)}
                  onFocus={() => setActiveDate(day)}
                  // The full date, because the visible text is a bare number and the weekday
                  // row is aria-hidden AND a sibling of the grid rather than columnheaders
                  // inside it — so a cell had no weekday, no month and no year to announce.
                  // aria-label is allowed on a gridcell, leaves the visible glyph alone, and is
                  // what every calendar in the APG's own examples effectively gives AT.
                  aria-label={formatFullDate(day, locale)}
                  data-terp="calendar-day"
                  data-in-range={inRange ? "true" : undefined}
                  data-outside-month={day.getMonth() === month.getMonth() ? undefined : "true"}
                >
                  {day.getDate()}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function useDateLocale() {
  return useLocale()?.locale;
}

// `formatDate` used to live here, three functions deep in a file about calendars, and it was the
// only general-purpose locale-correct date rendering in the package. It is `../format` now and
// imported back; the three below stay, because a spoken day, a grid caption and a column header
// are calendar parts rather than general formatting.
//
// They are cached for the reason `../format` caches its own: constructing an Intl formatter costs
// far more than using one — measured at roughly 55x on this repository's Node — and the spoken-day
// formatter runs once per DAY CELL, so an open calendar built 42 of them per render and a further
// seven for the column headers.
const CALENDAR_FORMATTERS = new Map<string, Intl.DateTimeFormat>();

function calendarFormatter(
  locale: string | undefined,
  kind: "full" | "month" | "weekday",
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = `${kind}|${locale ?? ""}`;
  let formatter = CALENDAR_FORMATTERS.get(key);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat(locale, options);
    CALENDAR_FORMATTERS.set(key, formatter);
  }
  return formatter;
}

/** The whole date, spoken: what a day cell announces, since its text is only a number. */
function formatFullDate(date: Date, locale: string | undefined) {
  return calendarFormatter(locale, "full", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}

function formatMonth(date: Date, locale: string | undefined) {
  return calendarFormatter(locale, "month", { year: "numeric", month: "long" }).format(date);
}

function weekdayNames(locale: string | undefined) {
  const base = new Date(2024, 0, 7);
  const formatter = calendarFormatter(locale, "weekday", { weekday: "short" });
  return Array.from({ length: 7 }, (_, index) => formatter.format(addDays(base, index)));
}

function normalizeRange(value: DateRangeValue): DateRangeValue {
  return { start: normalizeDate(value.start), end: normalizeDate(value.end) };
}
function normalizeDate(date: Date | null | undefined): Date | null {
  return date instanceof Date && !Number.isNaN(date.getTime()) ? new Date(date.getFullYear(), date.getMonth(), date.getDate()) : null;
}
function today() { return normalizeDate(new Date())!; }
function startOfMonth(date: Date) { return new Date(date.getFullYear(), date.getMonth(), 1); }
function addDays(date: Date, days: number) { return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days); }
function addMonths(date: Date, months: number) { return new Date(date.getFullYear(), date.getMonth() + months, 1); }
function daysInMonth(date: Date) { return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate(); }
function toKey(date: Date) { return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`; }
function sameDate(a: Date | null | undefined, b: Date | null | undefined) { return a !== null && a !== undefined && b !== null && b !== undefined && compareDate(a, b) === 0; }
function compareDate(a: Date, b: Date) { return a.getTime() - b.getTime(); }
function isDisabled(date: Date, min: Date | null, max: Date | null) { return (min !== null && compareDate(date, min) < 0) || (max !== null && compareDate(date, max) > 0); }
function clampDate(date: Date, min: Date | null, max: Date | null) {
  if (min !== null && compareDate(date, min) < 0) return min;
  if (max !== null && compareDate(date, max) > 0) return max;
  return date;
}
/** Six weeks of seven days covering `month`, the first cell being that month's Sunday-start. */
function monthWeeks(month: Date) {
  const first = startOfMonth(month);
  const start = addDays(first, -first.getDay());
  return Array.from({ length: 6 }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => addDays(start, week * 7 + day)),
  );
}
function isWithinRange(date: Date, range: DateRangeValue | undefined) {
  if (range?.start === null || range?.start === undefined || range.end === null || range.end === undefined) {
    return false;
  }
  return compareDate(date, range.start) >= 0 && compareDate(date, range.end) <= 0;
}
