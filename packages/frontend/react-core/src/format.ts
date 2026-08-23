import { useCallback } from "react";

import { useLocale } from "./locale";

/**
 * Locale-aware date and number formatting.
 *
 * Seven places in this package formatted a date with `toLocaleDateString()` or
 * `toLocaleString()` and no locale argument, which asks the *browser* what language to use. An app
 * that ships Dutch through `LocaleProvider` therefore rendered its own admin tables in whatever
 * the visitor's OS was set to, one row above a `DatePicker` that got it right — because the
 * correct helper already existed, private, in a file about calendars.
 *
 * That helper is now here, unchanged, and `DatePicker` imports it back. Adopting its exact shape
 * rather than inventing one is deliberate: it is the only date rendering in the package that was
 * already locale-correct, so it is the one that defines the house shape, and moving it moves no
 * pixels.
 *
 * Each formatter comes in two forms. The hook reads the app's locale from context and is what a
 * component should use; the plain function takes the locale explicitly, for a caller that already
 * has one or is not a component. The hooks are `useCallback`-stable so a column list built in a
 * `useMemo` can depend on one without rebuilding every render.
 */

/** Anything a record's date field plausibly arrives as. */
export type FormattableDate = Date | string | number | null | undefined;

/**
 * What an absent or unparseable date renders as.
 *
 * An em dash rather than an empty cell, because a blank reads as "still loading" in a table and as
 * a layout bug in a detail list. This is the glyph the audit screen already used for the same job.
 */
const EMPTY = "—";

/**
 * Parse without throwing, and treat an unparseable value as absent.
 *
 * `new Date("not a date")` yields an Invalid Date whose `format` throws a RangeError, so a single
 * malformed row from an API would take down the whole table rather than showing one dash.
 */
function toDate(value: FormattableDate): Date | null {
  if (value === null || value === undefined) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Locale-explicit short date, e.g. `7 jul 2026` under `nl`. `EMPTY` for absent or unparseable. */
export function formatDate(value: FormattableDate, locale: string | undefined): string {
  const date = toDate(value);
  return date === null
    ? EMPTY
    : new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric" }).format(
        date,
      );
}

/** The same date with the time of day, for a column whose subject is *when* something happened. */
export function formatDateTime(value: FormattableDate, locale: string | undefined): string {
  const date = toDate(value);
  return date === null
    ? EMPTY
    : new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

/** Locale-explicit number, with the grouping and decimal separators the locale expects. */
export function formatNumber(
  value: number | null | undefined,
  locale: string | undefined,
  options?: Intl.NumberFormatOptions,
): string {
  return value === null || value === undefined || Number.isNaN(value)
    ? EMPTY
    : new Intl.NumberFormat(locale, options).format(value);
}

/** {@link formatDate} bound to the app's locale. */
export function useFormatDate(): (value: FormattableDate) => string {
  const locale = useLocale()?.locale;
  return useCallback((value: FormattableDate) => formatDate(value, locale), [locale]);
}

/** {@link formatDateTime} bound to the app's locale. */
export function useFormatDateTime(): (value: FormattableDate) => string {
  const locale = useLocale()?.locale;
  return useCallback((value: FormattableDate) => formatDateTime(value, locale), [locale]);
}

/** {@link formatNumber} bound to the app's locale. */
export function useFormatNumber(): (
  value: number | null | undefined,
  options?: Intl.NumberFormatOptions,
) => string {
  const locale = useLocale()?.locale;
  return useCallback(
    (value: number | null | undefined, options?: Intl.NumberFormatOptions) =>
      formatNumber(value, locale, options),
    [locale],
  );
}
