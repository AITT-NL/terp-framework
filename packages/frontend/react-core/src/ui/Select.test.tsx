// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiTextProvider } from "../uiText";
import { Select } from "./Select";
import type { SelectOption } from "./Select";

afterEach(cleanup);

type Status = "open" | "doing" | "done";

const STATUSES: SelectOption<Status>[] = [
  { value: "open", label: "Open" },
  { value: "doing", label: "In progress" },
  { value: "done", label: "Done", disabled: true },
];

describe("Select — the options list", () => {
  it("renders one option per entry, in order, with the disabled flag applied", () => {
    render(<Select aria-label="Status" options={STATUSES} defaultValue="open" />);
    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => [option.value, option.textContent])).toEqual([
      ["open", "Open"],
      ["doing", "In progress"],
      ["done", "Done"],
    ]);
    // The flag has to reach the element rather than only the data, which is the half a
    // "renders three options" assertion would miss.
    expect(options.map((option) => option.disabled)).toEqual([false, false, true]);
  });

  it("resolves a label descriptor through the active resolver, not just a plain string", () => {
    // `label` is a UiText, so a translated catalog has to reach it — a component that
    // rendered `String(label)` would print "[object Object]" and this is what says so.
    render(
      <UiTextProvider resolveText={(text) => (typeof text === "string" ? text : `nl:${text.id}`)}>
        <Select
          aria-label="Status"
          options={[{ value: "open", label: { id: "status.open", message: "Open" } }]}
        />
      </UiTextProvider>,
    );
    expect(screen.getByRole("option")).toHaveTextContent("nl:status.open");
  });

  it("renders the placeholder as a disabled, empty-valued leading row", () => {
    render(<Select aria-label="Status" options={STATUSES} placeholder="Choose a status" />);
    const first = screen.getAllByRole("option")[0] as HTMLOptionElement;
    // All three properties matter: an enabled placeholder is selectable, and a non-empty
    // value would submit the prompt text as data.
    expect(first.textContent).toBe("Choose a status");
    expect(first.value).toBe("");
    expect(first.disabled).toBe(true);
  });

  it("hands onValueChange the selected value, and still fires the raw onChange", () => {
    const onValueChange = vi.fn();
    const onChange = vi.fn();
    render(
      <Select
        aria-label="Status"
        options={STATUSES}
        defaultValue="open"
        onValueChange={onValueChange}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "doing" } });
    expect(onValueChange).toHaveBeenCalledWith("doing");
    // Both, not one instead of the other: a caller that needs the element keeps its event.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]![0].target.value).toBe("doing");
  });

  it("calls onValueChange without an options list too", () => {
    // The typed callback is on the value props, not on the options branch, so the raw-children
    // form gets it as well. Worth pinning: putting it on one branch only would be the
    // works-in-one-branch defect the union exists to prevent.
    const onValueChange = vi.fn();
    render(
      <Select aria-label="Status" defaultValue="open" onValueChange={onValueChange}>
        <option value="open">Open</option>
        <option value="doing">In progress</option>
      </Select>,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "doing" } });
    expect(onValueChange).toHaveBeenCalledWith("doing");
  });
});

describe("Select — what did not change", () => {
  it("still renders raw option children unchanged, and carries the shared control marker", () => {
    render(
      <Select aria-label="Status" defaultValue="doing">
        <option value="open">Open</option>
        <option value="doing">In progress</option>
      </Select>,
    );
    const select = screen.getByRole("combobox");
    expect(select).toHaveAttribute("data-terp", "input");
    expect((select as HTMLSelectElement).value).toBe("doing");
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("renders no inline style in either form", () => {
    // ADR 0094 §3 as an assertion rather than a claim: the control's surface, the focus ring
    // and the chevron are all sheet rules keyed on `data-terp="input"`, and the inline-style
    // ledger is exact-equality per file — so a style attribute here would fail markers.test.ts
    // as well, one release later and further from the cause.
    const { container } = render(
      <>
        <Select aria-label="A" options={STATUSES} />
        <Select aria-label="B">
          <option value="open">Open</option>
        </Select>
      </>,
    );
    for (const select of container.querySelectorAll("select")) {
      expect(select.getAttribute("style")).toBeNull();
    }
  });

  it("forwards arbitrary select attributes to the element", () => {
    render(
      <Select aria-label="Status" options={STATUSES} name="status" required disabled />,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.name).toBe("status");
    expect(select.required).toBe(true);
    expect(select.disabled).toBe(true);
  });
});
