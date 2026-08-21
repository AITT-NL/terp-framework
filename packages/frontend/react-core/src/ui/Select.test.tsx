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

  it("shows the placeholder as the selected row, not just as an option", () => {
    // The selection is the assertion, and the markup-only version of this test was green
    // against a real bug. HTML's selectedness algorithm picks the first option that is NOT
    // disabled, so a disabled placeholder row is skipped and the control opens on the first
    // real choice: measured, `value=open, selectedIndex=1`, with a "Choose a status" row sitting
    // in the list that the user never saw. Every markup assertion below passed throughout.
    render(<Select aria-label="Status" options={STATUSES} placeholder="Choose a status" />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(select.selectedIndex).toBe(0);
    expect(select.options[0]!.textContent).toBe("Choose a status");
    // Still disabled and still empty-valued: an enabled placeholder is re-selectable, and a
    // non-empty value would submit the prompt text as data.
    expect(select.options[0]!.disabled).toBe(true);
    expect(select.options[0]!.value).toBe("");
  });

  it("lets an explicit value win over the placeholder", () => {
    // The other half: starting empty is a default for the unpinned case, not an override. A
    // caller who pins a value gets it, and the placeholder stays in the list as the row they
    // came from.
    render(
      <Select aria-label="Status" options={STATUSES} placeholder="Choose" defaultValue="doing" />,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("doing");
    expect(select.selectedIndex).toBe(2);
  });

  it("resolves a placeholder descriptor too, not only a plain string", () => {
    // `placeholder` is typed `UiText`, and a `string`-only version would have compiled just as
    // well while rendering "[object Object]" on screen — the string test above cannot tell the
    // two apart, so this is the assertion that can.
    //
    // (An earlier version of this comment claimed `SelectHTMLAttributes` already declares
    // `placeholder?: string` and that the union therefore intersects with it. It does not:
    // `placeholder` is declared on `AllHTMLAttributes`, `InputHTMLAttributes` and
    // `TextareaHTMLAttributes` only. There is no intersection here, and the prop is simply
    // ours.)
    render(
      <UiTextProvider resolveText={(text) => (typeof text === "string" ? text : `nl:${text.id}`)}>
        <Select
          aria-label="Status"
          options={STATUSES}
          placeholder={{ id: "status.choose", message: "Choose a status" }}
        />
      </UiTextProvider>,
    );
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("nl:status.choose");
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

  it("still accepts a multiple select with an array value", () => {
    // A regression this file exists to prevent, because it happened. The first version of the
    // options work put the narrowed `value?: T` on BOTH branches, which quietly made
    // `<Select multiple value={["a", "b"]}>` a typecheck error — a shape a raw `<select>` has
    // and this component had always accepted. Nothing in the repo used it, so no gate noticed;
    // it was found by probing the type rather than by running the suite.
    //
    // The narrowing only earns anything where `T` can be inferred, which is the options list.
    // So the raw-children branch keeps `SelectHTMLAttributes` untouched, and this case is the
    // assertion that says so. It has to COMPILE as much as pass.
    render(
      <Select aria-label="Tags" multiple value={["a", "b"]} onChange={() => {}}>
        <option value="a">A</option>
        <option value="b">B</option>
        <option value="c">C</option>
      </Select>,
    );
    const select = screen.getByRole("listbox") as HTMLSelectElement;
    expect(select.multiple).toBe(true);
    expect([...select.selectedOptions].map((option) => option.value)).toEqual(["a", "b"]);
  });

  it("still accepts a numeric value with numeric option children", () => {
    // The other shape the over-eager narrowing broke: `value?: string | number` is what
    // `SelectHTMLAttributes` declares, and a rank ladder rendered as numbers is the obvious
    // caller — `UserCreate` was written that way before it moved to an options list.
    render(
      <Select aria-label="Rank" value={20} onChange={() => {}}>
        <option value={10}>Viewer</option>
        <option value={20}>Editor</option>
      </Select>,
    );
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("20");
  });

  it("keeps React's own read-only diagnostic for a value with no handler", () => {
    // The change that removed this was an unconditional onChange wrapper: React's
    // `checkControlledValueProps` short-circuits on `props.onChange`, so attaching one always
    // silenced the "you provided a `value` prop to a form field without an `onChange` handler"
    // warning. The control then looked editable, never updated, and said nothing about it —
    // strictly worse than before the options list existed. The wrapper is attached only when
    // there is something to call.
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<Select aria-label="Status" options={STATUSES} value="open" />);
    const logged = errors.mock.calls.map((call) => String(call[0])).join(" ");
    errors.mockRestore();
    expect(logged).toContain("without an `onChange` handler");
  });

  it("still renders with neither options nor children", () => {
    // Legal before this component took an options list — a screen that renders its select
    // before its choices have loaded — so `children` stays optional on that branch. Making it
    // required was an unannounced breaking type change that nothing in the repo exercised.
    render(<Select aria-label="Empty" />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
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
