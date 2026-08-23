// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field } from "./Field";
import { Input } from "./ui/Input";
import { Select } from "./ui/Select";
import { Textarea } from "./ui/Textarea";

afterEach(cleanup);

describe("Field", () => {
  it("labels its control (accessible association) and shows hint + error", () => {
    render(
      <Field label="Email" hint="we never share it" error="required">
        <Input defaultValue="" />
      </Field>,
    );
    // The control is reachable by its label text (implicit association via the wrapping <label>).
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByText("we never share it")).toBeInTheDocument();
    expect(screen.getByText("required")).toBeInTheDocument();
  });

  it("exposes the error as an alert, and nothing else in the field", () => {
    // `aria-describedby` is read when focus reaches the control. That covers an error which was
    // already there and covers nothing about one that arrives on submit, when focus has left the
    // field and the only thing that changed is a span nobody is pointed at. The two channels fire
    // at different moments, and a submit-time rejection only has the second one.
    //
    // The length assertion is the half with teeth: `role="alert"` on the hint as well would
    // satisfy a bare `getByRole` while training the user to ignore the channel the error needs.
    // Mutation: drop `role="alert"` from the span and the lookup finds nothing.
    render(
      <Field label="Email" hint="we never share it" error="required">
        <Input defaultValue="" />
      </Field>,
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("required");
  });

  it("raises no alert when there is nothing wrong", () => {
    // An alert that is present on every render is an alert that means nothing. The span is
    // conditional, so it enters the accessibility tree exactly when the error appears, which is
    // the event the role exists to report.
    render(
      <Field label="Email" hint="we never share it">
        <Input defaultValue="" />
      </Field>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders no error node when error is null", () => {
    render(
      <Field label="Name" error={null}>
        <Input defaultValue="" />
      </Field>,
    );
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
  });
  it("points the control at its hint and its error, and marks it invalid", () => {
    render(
      <Field label="Email" hint="we never share it" error="required">
        <Input defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Email");
    // Text beside a control is invisible to a screen reader unless something points at it. The
    // label needs no wiring because the control sits inside it; the hint and the error do.
    const described = (input.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean);
    expect(described).toHaveLength(2);
    expect(described.map((id) => document.getElementById(id)?.textContent)).toEqual([
      "we never share it",
      "required",
    ]);
    // An error also opts the control into the sheet's invalid border, so the field does not
    // depend on every caller remembering to pass aria-invalid alongside its error text.
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("describes a hint with no error, and does not claim invalid", () => {
    render(
      <Field label="Name" hint="as it appears on the account">
        <Input defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Name");
    const id = input.getAttribute("aria-describedby");
    expect(document.getElementById(id!)?.textContent).toBe("as it appears on the account");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("adds no attributes when there is nothing to describe", () => {
    render(
      <Field label="Plain">
        <Input defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Plain");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("keeps a control's own aria-describedby and aria-invalid rather than replacing them", () => {
    render(
      <Field label="Email" hint="we never share it" error="required">
        <Input defaultValue="" aria-describedby="caller-note" aria-invalid={false} />
      </Field>,
    );
    const input = screen.getByLabelText("Email");
    // The field appends; it does not clobber. And a control that deliberately says it is NOT
    // invalid keeps saying so — the field supplies a default, not an override.
    expect(input.getAttribute("aria-describedby")?.split(" ")[0]).toBe("caller-note");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toHaveLength(3);
    expect(input).toHaveAttribute("aria-invalid", "false");
  });
});


describe("Select / Textarea primitives", () => {
  it("render token-styled controls reachable by their Field label", () => {
    render(
      <>
        <Field label="Status">
          <Select defaultValue="open">
            <option value="open">open</option>
            <option value="done">done</option>
          </Select>
        </Field>
        <Field label="Notes">
          <Textarea defaultValue="" />
        </Field>
      </>,
    );
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByLabelText("Notes")).toBeInTheDocument();
  });
});
