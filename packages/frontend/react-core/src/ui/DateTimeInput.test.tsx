// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Field } from "../Field";
import { DateTimeInput } from "./DateTimeInput";

afterEach(cleanup);

function pick(input: HTMLElement, wall: string) {
  fireEvent.change(input, { target: { value: wall } });
}

describe("DateTimeInput", () => {
  it("shows an instant as the wall time it reads as in the zone", () => {
    render(<DateTimeInput aria-label="Starts" value="2026-11-06T09:00:00Z" zone="Europe/Amsterdam" />);
    const input = screen.getByLabelText("Starts");
    expect(input).toHaveAttribute("type", "datetime-local");
    expect(input).toHaveAttribute("data-terp", "input");
    expect(input).toHaveValue("2026-11-06T10:00");
  });

  it("sends what is picked as the instant it names, with the zone's offset", () => {
    // The point of the control: a datetime-local value carries no offset, which the server
    // refuses (ADR 0206). What leaves here always names an instant.
    const onChange = vi.fn();
    render(<DateTimeInput aria-label="Starts" value={null} onChange={onChange} zone="Europe/Amsterdam" />);
    pick(screen.getByLabelText("Starts"), "2026-11-06T10:00");
    expect(onChange).toHaveBeenLastCalledWith("2026-11-06T10:00:00+01:00");
    pick(screen.getByLabelText("Starts"), "2026-07-01T10:00");
    expect(onChange).toHaveBeenLastCalledWith("2026-07-01T10:00:00+02:00");
  });

  it("sends null once the field is cleared", () => {
    const onChange = vi.fn();
    render(<DateTimeInput aria-label="Starts" value="2026-11-06T09:00:00Z" onChange={onChange} zone="UTC" />);
    pick(screen.getByLabelText("Starts"), "");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("moves a wall time the clocks skip forward past the gap", () => {
    // 29 March 2026: Amsterdam goes from 02:00 to 03:00, so 02:30 never happens there.
    const onChange = vi.fn();
    render(<DateTimeInput aria-label="Starts" value={null} onChange={onChange} zone="Europe/Amsterdam" />);
    pick(screen.getByLabelText("Starts"), "2026-03-29T02:30");
    expect(onChange).toHaveBeenLastCalledWith("2026-03-29T03:30:00+02:00");
  });

  it("takes the earlier of a wall time the clocks repeat", () => {
    // 25 October 2026: Amsterdam goes from 03:00 back to 02:00, so 02:30 happens twice.
    const onChange = vi.fn();
    render(<DateTimeInput aria-label="Starts" value={null} onChange={onChange} zone="Europe/Amsterdam" />);
    pick(screen.getByLabelText("Starts"), "2026-10-25T02:30");
    expect(onChange).toHaveBeenLastCalledWith("2026-10-25T02:30:00+02:00");
  });

  it("writes UTC with its Z, and a zone behind UTC with a negative offset", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <DateTimeInput aria-label="Starts" value={null} onChange={onChange} zone="UTC" />,
    );
    pick(screen.getByLabelText("Starts"), "2026-11-06T10:00");
    expect(onChange).toHaveBeenLastCalledWith("2026-11-06T10:00:00Z");
    rerender(<DateTimeInput aria-label="Starts" value={null} onChange={onChange} zone="America/St_Johns" />);
    pick(screen.getByLabelText("Starts"), "2026-11-06T10:00");
    expect(onChange).toHaveBeenLastCalledWith("2026-11-06T10:00:00-03:30");
  });

  it("reads in the browser's own zone when it is given none", () => {
    // The same instant the browser's own dates name for that wall time, whatever zone this
    // test runs in.
    const onChange = vi.fn();
    render(<DateTimeInput aria-label="Starts" value={null} onChange={onChange} />);
    pick(screen.getByLabelText("Starts"), "2026-11-06T10:00");
    const sent = onChange.mock.lastCall?.[0] as string;
    expect(Date.parse(sent)).toBe(new Date(2026, 10, 6, 10, 0).getTime());
  });

  it("shows a value without an offset as empty, since it names no instant", () => {
    render(<DateTimeInput aria-label="Starts" value="2026-11-06T10:00:00" zone="UTC" />);
    expect(screen.getByLabelText("Starts")).toHaveValue("");
    cleanup();
    render(<DateTimeInput aria-label="Starts" value="not a date+01:00" zone="UTC" />);
    expect(screen.getByLabelText("Starts")).toHaveValue("");
  });

  it("bounds the picker by instants, shown in the zone", () => {
    render(
      <DateTimeInput
        aria-label="Starts"
        value={null}
        zone="Europe/Amsterdam"
        min="2026-11-01T00:00:00Z"
        max="2026-11-30T23:00:00Z"
      />,
    );
    const input = screen.getByLabelText("Starts");
    expect(input).toHaveAttribute("min", "2026-11-01T01:00");
    expect(input).toHaveAttribute("max", "2026-12-01T00:00");
  });

  it("keeps what is picked itself when no value is given", () => {
    render(<DateTimeInput aria-label="Starts" defaultValue="2026-11-06T09:00:00Z" zone="UTC" />);
    const input = screen.getByLabelText("Starts");
    expect(input).toHaveValue("2026-11-06T09:00");
    pick(input, "2026-11-07T08:15");
    expect(input).toHaveValue("2026-11-07T08:15");
  });

  it("takes the label, hint and error a Field gives its control", () => {
    render(
      <Field label="Starts" hint="In Amsterdam time" error="Pick a time">
        <DateTimeInput value={null} zone="Europe/Amsterdam" />
      </Field>,
    );
    const input = screen.getByLabelText("Starts");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/In Amsterdam time/);
  });
});
