// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOCALE_EN, LOCALE_NL, LocaleProvider } from "../locale";
import { DatePicker, DateRangePicker } from "./DatePicker";

afterEach(cleanup);

describe("DatePicker", () => {
  it("selects a date and supports keyboard navigation", () => {
    const onChange = vi.fn();
    // Pinned to `en`: without a LocaleProvider the picker formats with
    // `Intl.DateTimeFormat(undefined, …)`, i.e. whatever locale the machine
    // running the suite happens to use — the month name below would then be
    // English only on an English host.
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" defaultValue={new Date(2026, 6, 7)} onChange={onChange} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Due date" }));
    expect(screen.getByRole("grid", { name: /July 2026/ })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("grid"), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("grid"), { key: "Enter" });
    expect(onChange.mock.calls[0]?.[0]).toEqual(new Date(2026, 6, 8));
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
  });

  // The ARIA shape and the roving cursor, both of which were wrong and neither of which
  // any lane could see: the calendar is only reachable through an open Popover, nothing in
  // the repo opened one, and the visual baselines capture resting state only.
  it("renders a valid grid of week rows, not 42 cells hanging off the grid", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" defaultValue={new Date(2026, 6, 7)} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Due date" }));
    const grid = screen.getByRole("grid");
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(6);
    // Owned by the grid, and owning the cells: `grid` requires `row` children and a
    // `gridcell` requires a `row` parent, so a flat grid fails both rules at once. Asserted
    // as a DOM relationship rather than a count, because 42 cells in the tree somewhere is
    // what the invalid version had too.
    for (const row of rows) {
      expect(row.parentElement).toBe(grid);
      expect(row.querySelectorAll('[role="gridcell"]')).toHaveLength(7);
    }
    expect(grid.querySelectorAll(':scope > [role="gridcell"]')).toHaveLength(0);
  });

  it("moves DOM focus with the roving cursor, not just tabIndex", async () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" defaultValue={new Date(2026, 6, 7)} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Due date" }));
    const grid = screen.getByRole("grid");
    const cursor = () => grid.querySelector<HTMLElement>('[tabindex="0"]');

    // Opening focuses the cursor (deferred a tick — the panel is portalled).
    await waitFor(() => expect(document.activeElement).toBe(cursor()));
    expect(cursor()?.textContent).toBe("7");

    fireEvent.keyDown(grid, { key: "ArrowRight" });
    expect(cursor()?.textContent).toBe("8");
    // The bug this pins: tabIndex moved and the browser's focus did not, so the focus ring
    // and every screen reader stayed on the day the calendar opened on.
    expect(document.activeElement).toBe(cursor());

    fireEvent.keyDown(grid, { key: "ArrowDown" });
    expect(cursor()?.textContent).toBe("15");
    expect(document.activeElement).toBe(cursor());
  });

  it("does not pull focus off the month buttons when they move the cursor", async () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" defaultValue={new Date(2026, 6, 7)} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Due date" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("grid").querySelector('[tabindex="0"]'),
      ),
    );
    // Changing month also moves the cursor. The follow is scoped to the grid rather than
    // the whole calendar precisely so this button keeps the focus the pointer gave it.
    const next = screen.getByRole("button", { name: "Next month" });
    next.focus();
    fireEvent.click(next);
    expect(screen.getByRole("grid", { name: /August 2026/ })).toBeInTheDocument();
    expect(document.activeElement).toBe(next);
  });

  it("opens the calendar on mount when asked", () => {
    // Sixteen calendar rules have been in the sheet since stage 2c with no way to render the
    // subtree, so neither visual lane had ever painted one. This is the way in.
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" value={new Date(2026, 6, 7)} defaultOpen />
      </LocaleProvider>,
    );
    expect(screen.getByRole("grid", { name: /July 2026/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Due date" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("names the calendar dialog with its month, and each day with its whole date", () => {
    render(
      <LocaleProvider locales={{ en: LOCALE_EN }}>
        <DatePicker aria-label="Due date" value={new Date(2026, 6, 7)} defaultOpen />
      </LocaleProvider>,
    );
    // A role="dialog" with no accessible name announces itself as "dialog" and nothing else.
    // The month was one level down on the grid, so it was reached only after the boundary had
    // already been crossed unnamed. axe does not report this at the wcag2a/aa tags the visual
    // suite runs, so opening the calendar did not surface it.
    expect(screen.getByRole("dialog", { name: /July 2026/ })).toBeInTheDocument();
    // And a day cell's visible text is a bare number, while the weekday row is aria-hidden AND
    // a sibling of the grid rather than columnheaders inside it — so a cell had no weekday, no
    // month and no year to announce.
    expect(
      screen.getByRole("gridcell", { name: "Tuesday, July 7, 2026" }),
    ).toBeInTheDocument();
  });

  it("uses the active locale for month and weekday names", () => {
    render(
      <LocaleProvider locales={{ nl: LOCALE_NL }}>
        <DatePicker aria-label="Datum" defaultValue={new Date(2026, 6, 7)} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Datum" }));
    expect(screen.getByRole("grid", { name: /juli 2026/i })).toBeInTheDocument();
    expect(screen.getByText(/zo/i)).toBeInTheDocument();
  });
});

describe("DateRangePicker", () => {
  it("opens the calendar on mount when asked", () => {
    render(
      <DateRangePicker
        aria-label="Window"
        value={{ start: new Date(2026, 6, 10), end: new Date(2026, 6, 14) }}
        defaultOpen
      />,
    );
    expect(screen.getByRole("grid")).toBeInTheDocument();
    // Both endpoints are selected and the days between them carry the range attribute — the
    // only surface in the package that paints either, and now the only one with a baseline.
    expect(screen.getByRole("grid").querySelectorAll('[aria-selected="true"]')).toHaveLength(2);
    expect(
      screen.getByRole("grid").querySelectorAll('[data-in-range="true"]').length,
    ).toBeGreaterThan(0);
  });

  // Day cells are matched by the text a user sees rather than by accessible name: the name is
  // now the whole date, and these two tests mount no LocaleProvider, so a name-based query
  // would depend on the host machine's locale.
  const dayCells = (text: string) =>
    screen.getAllByRole("gridcell").filter((cell) => cell.textContent === text);

  it("selects a start/end range and closes after the end", () => {
    const onChange = vi.fn();
    render(<DateRangePicker aria-label="Window" defaultValue={{ start: new Date(2026, 6, 10), end: null }} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Window" }));
    fireEvent.click(dayCells("12")[0]!);
    expect(onChange).toHaveBeenCalledWith({ start: new Date(2026, 6, 10), end: new Date(2026, 6, 12) });
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
  });

  it("restarts the range when selecting an end before the start and enforces min/max", () => {
    const onChange = vi.fn();
    render(
      <DateRangePicker
        aria-label="Window"
        defaultValue={{ start: new Date(2026, 6, 10), end: null }}
        min={new Date(2026, 6, 5)}
        max={new Date(2026, 6, 20)}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Window" }));
    expect(dayCells("4")[0]).toBeDisabled();
    fireEvent.click(dayCells("8")[0]!);
    expect(onChange).toHaveBeenCalledWith({ start: new Date(2026, 6, 8), end: null });
  });
});
