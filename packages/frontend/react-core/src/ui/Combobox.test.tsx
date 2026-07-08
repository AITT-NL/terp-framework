// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Field } from "../Field";
import { Combobox } from "./Combobox";

const options = [
  { value: "nl", label: "Netherlands" },
  { value: "be", label: "Belgium" },
  { value: "de", label: "Germany", disabled: true },
  { value: "fr", label: "France" },
];

afterEach(cleanup);

describe("Combobox", () => {
  it("filters options and selects an uncontrolled value", () => {
    const onChange = vi.fn();
    render(<Combobox aria-label="Country" options={options} onChange={onChange} />);
    const input = screen.getByRole("combobox", { name: /Country/ });
    expect(input).toHaveAttribute("aria-expanded", "false");
    fireEvent.focus(input);
    expect(input).toHaveAttribute("aria-expanded", "true");
    fireEvent.change(input, { target: { value: "bel" } });
    expect(screen.getByRole("option", { name: "Belgium" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "France" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Belgium" }));
    expect(input).toHaveValue("Belgium");
    expect(onChange).toHaveBeenCalledWith("be", options[1]);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports controlled value, Field labels, ARIA active option and keyboard navigation", () => {
    const onChange = vi.fn();
    render(
      <Field label="Country" error="Required">
        <Combobox options={options} value="nl" onChange={onChange} aria-invalid />
      </Field>,
    );
    const input = screen.getByRole("combobox", { name: /Country/ });
    expect(input).toHaveValue("Netherlands");
    expect(input).toHaveAttribute("aria-invalid", "true");
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", expect.stringContaining("be"));
    fireEvent.keyDown(input, { key: "End" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("fr", options[3]);
    expect(input).toHaveValue("Netherlands");
  });

  it("shows loading and disabled states", () => {
    render(<Combobox aria-label="Assignee" options={[]} loading disabled />);
    expect(screen.getByRole("combobox", { name: "Assignee" })).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
