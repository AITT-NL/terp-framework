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
  it("selects a start/end range and closes after the end", () => {
    const onChange = vi.fn();
    render(<DateRangePicker aria-label="Window" defaultValue={{ start: new Date(2026, 6, 10), end: null }} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Window" }));
    fireEvent.click(screen.getByRole("gridcell", { name: "12" }));
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
    expect(screen.getAllByRole("gridcell", { name: "4" })[0]).toBeDisabled();
    fireEvent.click(screen.getAllByRole("gridcell", { name: "8" })[0]);
    expect(onChange).toHaveBeenCalledWith({ start: new Date(2026, 6, 8), end: null });
  });
});
