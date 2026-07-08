// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOCALE_NL, LocaleProvider } from "../locale";
import { DatePicker, DateRangePicker } from "./DatePicker";

afterEach(cleanup);

describe("DatePicker", () => {
  it("selects a date and supports keyboard navigation", () => {
    const onChange = vi.fn();
    render(<DatePicker aria-label="Due date" defaultValue={new Date(2026, 6, 7)} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Due date" }));
    expect(screen.getByRole("grid", { name: /July 2026/ })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("grid"), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("grid"), { key: "Enter" });
    expect(onChange.mock.calls[0]?.[0]).toEqual(new Date(2026, 6, 8));
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
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
