// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UiTextProvider } from "../uiText";
import { Checkbox } from "./Checkbox";
import { RadioGroup } from "./Radio";
import { Switch } from "./Switch";

afterEach(cleanup);

/**
 * The three controls that label themselves, and therefore cannot use `Field`.
 *
 * Each renders its own `<label>` (or a `<fieldset>`/`<legend>`) around the input, so nesting
 * one inside `Field` produces a `<label>` within a `<label>` — invalid HTML that browsers
 * resolve by associating the control with the outer one, losing the field's label text. The
 * envelope had to be given to them separately; these hold that "separately" did not become
 * "differently".
 */
describe.each([
  ["Switch", "switch", (props: Record<string, unknown>) => <Switch label="Active" {...props} />],
  [
    "Checkbox",
    "checkbox",
    (props: Record<string, unknown>) => <Checkbox label="Active" {...props} />,
  ],
] as const)("%s hint and error", (_name, role, renderControl) => {
  it("points the control at its hint, so a screen reader reaches text beside it", () => {
    render(renderControl({ hint: "only affects new records" }));

    const control = screen.getByRole(role, { name: "Active" });
    const describedBy = control.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    // Text beside a control is invisible to assistive technology unless something points at
    // it — the association is the whole feature, not the rendering.
    expect(document.getElementById(describedBy as string)).toHaveTextContent(
      "only affects new records",
    );
  });

  it("marks the control invalid and announces the error when one arrives", () => {
    render(renderControl({ error: "you must accept this" }));

    const control = screen.getByRole(role, { name: "Active" });
    expect(control).toHaveAttribute("aria-invalid", "true");
    // `role="alert"` is not redundant with aria-describedby: a description is read when focus
    // reaches the control, which says nothing about an error that appears on submit, once
    // focus has already left.
    expect(screen.getByRole("alert")).toHaveTextContent("you must accept this");
  });

  it("adds to a caller's own description rather than replacing it", () => {
    render(
      renderControl({ hint: "field hint", "aria-describedby": "callers-own-node" }),
    );

    const control = screen.getByRole(role, { name: "Active" });
    const ids = (control.getAttribute("aria-describedby") ?? "").split(" ");
    expect(ids).toContain("callers-own-node");
    expect(ids.length).toBe(2);
  });

  it("keeps its state when an error appears, because the wrapper is not conditional", () => {
    // The regression this guards: rendering the wrapper only when there is a message changes
    // the element type at that position, so React unmounts the label and mounts a fresh
    // input. An uncontrolled control would lose what the user had done to it at exactly the
    // moment the form told them something was wrong.
    const { rerender } = render(renderControl({ defaultChecked: false }));
    const control = screen.getByRole(role, { name: "Active" });
    fireEvent.click(control);
    expect(screen.getByRole(role, { name: "Active" })).toBeChecked();

    rerender(renderControl({ defaultChecked: false, error: "required" }));

    expect(screen.getByRole(role, { name: "Active" })).toBeChecked();
  });
});

describe("RadioGroup hint and error", () => {
  const OPTIONS = [
    { value: "daily", label: "Daily" },
    { value: "weekly", label: "Weekly" },
  ];

  it("describes and invalidates the GROUP, not each option", () => {
    // The unanswered thing is the question, not any one radio. Describing each option would
    // repeat the message on every arrow-key move through the group.
    render(<RadioGroup label="Frequency" options={OPTIONS} error="choose one" />);

    const group = screen.getByRole("group", { name: "Frequency" });
    expect(group).toHaveAttribute("aria-invalid", "true");
    const describedBy = group.getAttribute("aria-describedby");
    expect(document.getElementById(describedBy as string)).toHaveTextContent("choose one");

    for (const option of screen.getAllByRole("radio")) {
      expect(option).not.toHaveAttribute("aria-invalid");
      expect(option).not.toHaveAttribute("aria-describedby");
    }
  });

  it("is the control of the three with a real error need", () => {
    // A boolean cannot hold a value its type refuses, so a switch has little to be wrong
    // about. A required radio group CAN be left unset, and before this prop that rejection
    // had nowhere to go but a form-level summary that never names the question it is about.
    render(<RadioGroup label="Frequency" options={OPTIONS} error="choose one" />);

    expect(screen.queryByRole("radio", { checked: true })).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("choose one");
  });

  it("renders no description at all when there is nothing to say", () => {
    render(<RadioGroup label="Frequency" options={OPTIONS} />);

    const group = screen.getByRole("group", { name: "Frequency" });
    expect(group).not.toHaveAttribute("aria-describedby");
    expect(group).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("resolves a translated hint descriptor", () => {
    render(
      <UiTextProvider
        resolveText={(text) => (typeof text === "string" ? text : `translated:${text.id}`)}
      >
        <RadioGroup
          label="Frequency"
          options={OPTIONS}
          hint={{ id: "billing.frequency.hint", message: "You can change this later" }}
        />
      </UiTextProvider>,
    );

    expect(screen.getByText("translated:billing.frequency.hint")).toBeInTheDocument();
  });
});
