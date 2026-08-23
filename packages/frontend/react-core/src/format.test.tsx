// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ReactNode } from "react";

import { DataView } from "./dataview";
import { InMemoryDataViewRepository } from "./dataview";
import type { DataViewColumn } from "./dataview";
import {
  formatDate,
  formatDateTime,
  formatNumber,
  useFormatDate,
  useFormatNumber,
} from "./format";
import { LocaleProvider } from "./locale";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

// Midday UTC on purpose: an instant near either edge of the day lands on a different calendar date
// depending on the runner's zone, which would make a date assertion fail somewhere and nowhere else.
const WHEN = "2026-07-07T12:00:00Z";

const NL = { label: "Nederlands", strings: {} };
const EN = { label: "English", strings: {} };

describe("the locale-explicit formatters", () => {
  it("actually varies with the locale it is given", () => {
    // The whole defect was a missing argument, so the assertion that matters is that the argument
    // changes the answer. Comparing against one hard-coded string would pass just as happily if
    // the locale were ignored and both calls fell through to the runner's default.
    const dutch = formatDate(WHEN, "nl");
    const american = formatDate(WHEN, "en-US");
    expect(dutch).not.toBe(american);
    // Day-first versus month-first is the visible difference, and it survives an ICU update in a
    // way that an exact string does not.
    expect(dutch.startsWith("7")).toBe(true);
    expect(american.startsWith("Jul")).toBe(true);
  });

  it("adds a time of day only in the date-time form", () => {
    // The audit log's column is titled "when"; dropping its clock would be a silent downgrade.
    expect(formatDateTime(WHEN, "en-US")).toMatch(/\d{1,2}:\d{2}/);
    expect(formatDate(WHEN, "en-US")).not.toMatch(/\d{1,2}:\d{2}/);
  });

  it("groups and separates numbers the way the locale does", () => {
    expect(formatNumber(1234.5, "nl")).not.toBe(formatNumber(1234.5, "en-US"));
    expect(formatNumber(1234.5, "en-US")).toBe("1,234.5");
  });

  it("renders an em dash for nothing, rather than throwing or printing Invalid Date", () => {
    // `new Date("whenever")` yields an Invalid Date whose `format` throws a RangeError, so one
    // malformed row from an API would take down a whole table instead of showing one dash.
    for (const value of [null, undefined, "", "not a date", Number.NaN]) {
      expect(formatDate(value, "nl")).toBe("—");
      expect(formatDateTime(value, "nl")).toBe("—");
    }
    expect(formatNumber(null, "nl")).toBe("—");
    expect(formatNumber(Number.NaN, "nl")).toBe("—");
  });

  it("accepts the three shapes a date field arrives in", () => {
    const iso = formatDate(WHEN, "en-US");
    expect(formatDate(new Date(WHEN), "en-US")).toBe(iso);
    expect(formatDate(new Date(WHEN).getTime(), "en-US")).toBe(iso);
  });
});

function ShownDate() {
  return <p data-testid="shown">{useFormatDate()(WHEN)}</p>;
}

function ShownNumber() {
  return <p data-testid="shown">{useFormatNumber()(1234.5)}</p>;
}

/** Render `body` under one app locale and return what it printed. */
function shownUnder(locale: string, body: ReactNode): string {
  const { unmount } = render(
    <LocaleProvider locales={{ nl: NL, "en-US": EN }} defaultLocale={locale}>
      {body}
    </LocaleProvider>,
  );
  const text = screen.getByTestId("shown").textContent ?? "";
  unmount();
  return text;
}

describe("the hooks", () => {
  // These compare TWO app locales against each other rather than one against an expected string,
  // and the reason is worth stating because the first version of this file did the latter and a
  // mutation proved it worthless. This machine's Node resolves to nl-NL, so
  // `formatDate(value, undefined)` and `formatDate(value, "nl")` are the same string: a test that
  // rendered a Dutch provider and asserted the Dutch spelling passed with the hook ignoring its
  // locale entirely. It would have failed on an English host and passed here, which is worse than
  // no test. Two locales cannot agree unless the locale is being dropped, on any host.

  it("reads the app's locale, not the machine's", () => {
    const dutch = shownUnder("nl", <ShownDate />);
    const american = shownUnder("en-US", <ShownDate />);
    expect(dutch).not.toBe(american);
    expect(dutch).toBe(formatDate(WHEN, "nl"));
    expect(american).toBe(formatDate(WHEN, "en-US"));
  });

  it("formats numbers through the same locale", () => {
    const dutch = shownUnder("nl", <ShownNumber />);
    const american = shownUnder("en-US", <ShownNumber />);
    expect(dutch).not.toBe(american);
    expect(american).toBe("1,234.5");
  });

  it("falls back to the runtime default outside a LocaleProvider", () => {
    // `useLocale()` returns null with no provider, and that must mean "let Intl decide" rather
    // than throw: `Field`, `DataView` and the admin screens all render fine without one.
    render(<ShownDate />);
    expect(screen.getByTestId("shown")).toHaveTextContent(formatDate(WHEN, undefined));
  });
});

interface Dated {
  id: string;
  when: Date;
}

describe("a Date in a cell", () => {
  it("is formatted for the locale instead of stringified", async () => {
    // `accessor` returns `unknown`, so a Date is type-legal, and `String(value)` renders
    // "Tue Jul 07 2026 14:00:00 GMT+0200 (Central European Summer Time)" into a table cell.
    // Nothing in this tree returns a Date today, which is why this is the only thing standing
    // between an app that does and that string.
    const when = new Date(WHEN);
    const columns: DataViewColumn<Dated>[] = [
      { id: "when", header: "When", accessor: (row) => row.when, meta: { mobileSlot: "title" } },
    ];
    const repository = new InMemoryDataViewRepository([{ id: "1", when }], {
      getRowId: (row) => row.id,
      getValue: (row, column) => row[column as keyof Dated],
    });
    render(
      <LocaleProvider locales={{ nl: NL }} defaultLocale="nl">
        <DataView<Dated> repository={repository} columns={columns} />
      </LocaleProvider>,
    );
    expect(await screen.findByText(formatDate(when, "nl"))).toBeInTheDocument();
    expect(screen.queryByText(String(when))).toBeNull();
  });
});
