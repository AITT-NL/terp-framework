import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useLocale } from "../locale";
import { injectTerpStyles } from "../styles";
import { useUiText } from "../uiText";
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
}

/** Single-date calendar picker with locale-aware labels and keyboard navigation. */
export function DatePicker({
  value,
  defaultValue = null,
  onChange,
  min,
  max,
  disabled = false,
  placeholder = "Select date",
  "aria-label": ariaLabel,
  "aria-invalid": ariaInvalid,
}: DatePickerProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState<Date | null>(defaultValue);
  const selected = normalizeDate(value ?? uncontrolledValue);
  const [open, setOpen] = useState(false);
  const locale = useDateLocale();
  const resolve = useUiText();
  const formatted = selected === null ? resolve(placeholder) : formatDate(selected, locale);

  function commit(next: Date) {
    if (value === undefined) {
      setUncontrolledValue(next);
    }
    onChange?.(next);
    setOpen(false);
  }

  return (
    <Popover
      open={open}
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
  placeholder = "Select date range",
  "aria-label": ariaLabel,
  "aria-invalid": ariaInvalid,
}: DateRangePickerProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState<DateRangeValue>(defaultValue);
  const selected = normalizeRange(value ?? uncontrolledValue);
  const [open, setOpen] = useState(false);
  const locale = useDateLocale();
  const resolve = useUiText();
  const formatted = selected.start === null
    ? resolve(placeholder)
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
      open={open}
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
  const gridId = useId();
  const minDate = normalizeDate(min);
  const maxDate = normalizeDate(max);
  const initial = clampDate(normalizeDate(visibleSeed) ?? today(), minDate, maxDate);
  const [month, setMonth] = useState(() => startOfMonth(initial));
  const [activeDate, setActiveDate] = useState(initial);
  const activeRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);
  const weeks = useMemo(() => monthWeeks(month), [month]);
  const weekdays = useMemo(() => weekdayNames(locale), [locale]);
  const activeKey = toKey(activeDate);

  // The roving cursor has to move DOM focus, not just `tabIndex`. This effect used to
  // carry an empty dependency list, so it focused the initial day once and never again:
  // an arrow key moved `activeDate`, which moved `tabIndex={0}` and `activeRef` to
  // another cell, while the browser's focus — and therefore the caret, the focus ring
  // and every screen reader — stayed on the day the calendar opened on. Keyed on the
  // cursor now, so each move follows it.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      // The panel is portalled and Popover positions it in a layout effect, so the
      // opening focus waits a tick for the cell to exist where it will finally sit.
      const timer = window.setTimeout(() => activeRef.current?.focus(), 0);
      return () => window.clearTimeout(timer);
    }
    // Only while the grid already owns focus: `activeDate` also moves on a cell's own
    // `onFocus`, and on a month change from the header buttons — which must not yank
    // focus off the button the pointer just pressed.
    if (gridRef.current?.contains(document.activeElement) === true) {
      activeRef.current?.focus();
    }
    return undefined;
  }, [activeKey]);

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
        move(1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        move(-1);
        break;
      case "ArrowDown":
        event.preventDefault();
        move(7);
        break;
      case "ArrowUp":
        event.preventDefault();
        move(-7);
        break;
      case "Home":
        event.preventDefault();
        move(-activeDate.getDay());
        break;
      case "End":
        event.preventDefault();
        move(6 - activeDate.getDay());
        break;
      case "PageUp":
        event.preventDefault();
        changeMonth(-1);
        break;
      case "PageDown":
        event.preventDefault();
        changeMonth(1);
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
    <div role="dialog" aria-modal="false" data-terp="calendar">
      <div data-terp="calendar-header">
        <button type="button" data-terp="iconbutton" aria-label="Previous month" onClick={() => changeMonth(-1)}>‹</button>
        <div data-terp="calendar-title">{formatMonth(month, locale)}</div>
        <button type="button" data-terp="iconbutton" aria-label="Next month" onClick={() => changeMonth(1)}>›</button>
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
        ref={gridRef}
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

function formatDate(date: Date, locale: string | undefined) {
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric" }).format(date);
}

function formatMonth(date: Date, locale: string | undefined) {
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "long" }).format(date);
}

function weekdayNames(locale: string | undefined) {
  const base = new Date(2024, 0, 7);
  return Array.from({ length: 7 }, (_, index) => new Intl.DateTimeFormat(locale, { weekday: "short" }).format(addDays(base, index)));
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
