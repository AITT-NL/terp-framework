// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field, FieldRow } from "./Field";
import { TERP_STYLES_CSS } from "./styles";
import { UiTextProvider } from "./uiText";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import { Select } from "./ui/Select";
import { Textarea } from "./ui/Textarea";

afterEach(cleanup);

describe("Field", () => {
  it("resolves a descriptor used as helper text", () => {
    render(
      <UiTextProvider
        resolveText={(text) =>
          typeof text === "string" ? text : `translated:${text.id}`
        }
      >
        <Field
          label="Email"
          hint={{ id: "account.email.hint", message: "We never share it" }}
        >
          <Input />
        </Field>
      </UiTextProvider>,
    );

    expect(screen.getByText("translated:account.email.hint")).toBeInTheDocument();
  });

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

  it("emits no messages envelope for a field that has nothing to say", () => {
    // The guard that makes the envelope safe to add at all. Emitted unconditionally it
    // would put a grid row and a gap inside every field in every app carrying neither a
    // hint nor an error -- which is most of them -- and the change would arrive as a few
    // pixels of drift on screens nobody touched. Asserted as absence, because a present
    // but empty box is exactly the failure and it renders as nothing visible.
    render(
      <Field label="Plain">
        <Input />
      </Field>,
    );
    expect(
      document.querySelector('[data-terp="field-messages"]'),
      "a field with no messages renders the DOM it rendered before",
    ).toBeNull();
  });

  it("puts a hint and an error in one envelope, still described and still an alert", () => {
    // Both in one box, which is what lets a field occupy a single messages LINE inside a
    // FieldRow -- two loose spans would take two of the row's three lines and push every
    // other field's control down with them.
    //
    // The wiring has to survive the move, and the two halves survive for different
    // reasons: the control must be described by BOTH ids, and the error must keep
    // role="alert", because aria-describedby is read when focus arrives and says nothing
    // about an error that appears on submit. Dropping either would be invisible here
    // without asserting it.
    render(
      <Field label="Both" hint="A hint" error="Required.">
        <Input />
      </Field>,
    );
    const envelope = document.querySelector('[data-terp="field-messages"]');
    expect(envelope, "one envelope holds both").not.toBeNull();
    const hint = envelope!.querySelector('[data-terp="field-hint"]')!;
    const error = envelope!.querySelector('[data-terp="field-error"]')!;
    expect(hint.textContent).toBe("A hint");
    expect(error.textContent).toBe("Required.");
    expect(error.getAttribute("role")).toBe("alert");

    const control = screen.getByLabelText("Both");
    const described = (control.getAttribute("aria-describedby") ?? "").split(" ");
    expect(described, "the hint is still pointed at").toContain(hint.id);
    expect(described, "and so is the error").toContain(error.id);
    expect(control.getAttribute("aria-invalid")).toBe("true");
  });

  it("gives a FieldRow its fields and leaves everything else as itself", () => {
    // The row is a PLACEMENT, not a wrapper: a child that is not a field keeps its own
    // element and its own accessible name, and the sheet moves it to the control line by
    // selector rather than by nesting it in something. Asserted on the DOM because that is
    // this lane's half -- the tracks are pinned in styles.test.ts and the measured result
    // in the workbench's computed lane.
    render(
      <FieldRow>
        <Field label="A">
          <Input />
        </Field>
        <Field label="B" hint="Why">
          <Input />
        </Field>
        <Button>Remove</Button>
      </FieldRow>,
    );
    const row = document.querySelector('[data-terp="field-row"]')!;
    expect(row.querySelectorAll('[data-terp="field"]')).toHaveLength(2);
    expect(
      row.querySelector("button"),
      "a non-field child is rendered as itself, not wrapped",
    ).toBe(screen.getByRole("button", { name: "Remove" }));
    // The default gap stamps nothing, so the base rule stands rather than being restated
    // in the DOM -- the idiom Stack, Grid and DetailList all use.
    expect(row.getAttribute("data-gap")).toBeNull();
  });

  it("stamps a FieldRow gap the sheet actually has a rule for", () => {
    // A gap whose roll-call entry is missing stamps an attribute that styles nothing, which
    // is a prop that silently does not work. The token set is closed, so this reads the
    // sheet rather than trusting the type to have been kept in step with it.
    render(
      <FieldRow gap={4}>
        <Field label="C">
          <Input />
        </Field>
      </FieldRow>,
    );
    expect(document.querySelector('[data-terp="field-row"]')!.getAttribute("data-gap")).toBe(
      "4",
    );
    expect(TERP_STYLES_CSS).toContain('[data-terp="field-row"][data-gap="4"]');
  });
});
