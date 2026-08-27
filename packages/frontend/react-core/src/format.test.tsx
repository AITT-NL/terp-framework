// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "./locale";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

// Midday UTC keeps the calendar date stable across most zones, but only most: UTC+13 and UTC+14
// exist (Pacific/Apia, Pacific/Kiritimati), so at 12:00Z the local date there is already the 8th.
// No assertion below depends on WHICH day it is — the locale assertions compare two locales against
// each other, and the shape assertions ask whether the day or the month comes first. An earlier
// version asserted the literal digit 7 and would have failed in Kiritimati and nowhere else.
const WHEN = "2026-07-07T12:00:00Z";

const NL = LOCALE_NL;
const EN = LOCALE_EN;

describe("the locale-explicit formatters", () => {
  it("actually varies with the locale it is given", () => {
    // The whole defect was a missing argument, so the assertion that matters is that the argument
    // changes the answer. Comparing against one hard-coded string would pass just as happily if
    // the locale were ignored and both calls fell through to the runner's default.
    const dutch = formatDate(WHEN, "nl");
    const american = formatDate(WHEN, "en-US");
    expect(dutch).not.toBe(american);
    // Day-first versus month-first is the visible difference, and it survives both an ICU update
    // and a runner in a zone where the local calendar date is already the next day.
    expect(dutch).toMatch(/^\d/);
    expect(american).toMatch(/^[A-Za-z]/);
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

  it("builds one formatter per locale, not one per value", () => {
    // Constructing an Intl formatter costs ~55x using one, and every table cell comes through
    // here, so the first version of this file turned a locale fix into a rendering cost: a 200-row
    // table with three date columns built 600 formatters per render. Counting constructions is the
    // only way to see it — the output is identical either way, which is exactly why it shipped.
    const original = Intl.DateTimeFormat;
    let constructed = 0;
    try {
      (Intl as { DateTimeFormat: unknown }).DateTimeFormat = function counted(
        ...args: ConstructorParameters<typeof Intl.DateTimeFormat>
      ) {
        constructed += 1;
        return new original(...args);
      };
      for (let index = 0; index < 50; index += 1) {
        formatDate(`2026-07-${String((index % 28) + 1).padStart(2, "0")}T12:00:00Z`, "en-GB");
      }
      expect(constructed).toBe(1);
      // A second locale is a second formatter, not a cache that answers with the wrong one.
      formatDate(WHEN, "en-IE");
      expect(constructed).toBe(2);
    } finally {
      (Intl as { DateTimeFormat: unknown }).DateTimeFormat = original;
    }
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

const DATED_COLUMNS: DataViewColumn<Dated>[] = [
  { id: "when", header: "When", accessor: (row) => row.when, meta: { mobileSlot: "title" } },
];

function datedView(locale: string, when: Date) {
  const repository = new InMemoryDataViewRepository([{ id: "1", when }], {
    getRowId: (row) => row.id,
    getValue: (row, column) => row[column as keyof Dated],
  });
  return (
    <LocaleProvider locales={{ nl: NL, "en-US": EN }} defaultLocale={locale}>
      <DataView<Dated> repository={repository} columns={DATED_COLUMNS} />
    </LocaleProvider>
  );
}

describe("a Date in a cell", () => {
  // Rendered under BOTH locales, for the reason stated at the top of the hook block: the runner is
  // nl-NL, so a single Dutch render would go green with `useCellFormatter` ignoring its locale
  // entirely. That is what the first version of this test did — twenty lines under a comment
  // explaining why not to. Two locales cannot both be right unless the locale is being read.
  const when = new Date(WHEN);

  it("guards its own premise: the two spellings differ", () => {
    expect(formatDate(when, "nl")).not.toBe(formatDate(when, "en-US"));
  });

  it("is formatted for the app's locale instead of stringified — table view", async () => {
    // `accessor` returns `unknown`, so a Date is type-legal, and `String(value)` renders
    // "Tue Jul 07 2026 14:00:00 GMT+0200 (Central European Summer Time)" into a table cell.
    render(datedView("en-US", when));
    expect(await screen.findByText(formatDate(when, "en-US"))).toBeInTheDocument();
    expect(screen.queryByText(formatDate(when, "nl"))).toBeNull();
    expect(screen.queryByText(String(when))).toBeNull();
    cleanup();

    render(datedView("nl", when));
    expect(await screen.findByText(formatDate(when, "nl"))).toBeInTheDocument();
    expect(screen.queryByText(formatDate(when, "en-US"))).toBeNull();
  });

  it("is formatted for the app's locale instead of stringified — card view", async () => {
    // The stated reason for extracting `useCellFormatter` was that the two renderers had drifted
    // apart unnoticed, so pinning only the desktop one would reproduce the defect the extraction
    // was for. `DataView` reads `matchMedia` to pick a layout and jsdom always says no, so the
    // card list is only reachable through the explicit toggle.
    render(datedView("en-US", when));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Card view" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(formatDate(when, "en-US"))).toBeInTheDocument();
    expect(screen.queryByText(formatDate(when, "nl"))).toBeNull();
    expect(screen.queryByText(String(when))).toBeNull();
  });
});
