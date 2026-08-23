// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field } from "../Field";
import { Input } from "./Input";

afterEach(cleanup);

describe("Input", () => {
  it("renders a bare input for every type but password", () => {
    // The wrapper exists for exactly one type. Two child selectors in the sheet reach for
    // `data-terp="input"` as a DIRECT child — the toolbar search and the resource-list create
    // field — and both would break against a wrapper, so "only password wraps" is a fact those
    // rules depend on rather than an implementation detail.
    const { container, rerender } = render(<Input type="text" defaultValue="" />);
    expect(container.firstElementChild?.tagName).toBe("INPUT");
    rerender(<Input type="search" defaultValue="" />);
    expect(container.firstElementChild?.tagName).toBe("INPUT");
    rerender(<Input defaultValue="" />);
    expect(container.firstElementChild?.tagName).toBe("INPUT");
    rerender(<Input type="password" defaultValue="" />);
    expect(container.firstElementChild?.getAttribute("data-terp")).toBe("input-password");
  });

  it("reveals and re-hides the value, and its NAME is what says which it will do", () => {
    // One encoding of the state, not two. The name swaps, and there is deliberately no
    // `aria-pressed`: a toggle announced as "Hide password, pressed" claims the value is hidden
    // and shown at once. It also keeps this button outside the sheet's shared hover guard, which
    // excludes `[aria-pressed="true"]` and would leave the revealed toggle with no hover at all.
    render(<Input type="password" aria-label="Password" defaultValue="hunter2" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).not.toHaveAttribute("aria-pressed");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    const now = screen.getByRole("button", { name: "Hide password" });
    expect(now).not.toHaveAttribute("aria-pressed");
    fireEvent.click(now);
    expect(input).toHaveAttribute("type", "password");
  });

  it("does not submit the form it sits in", () => {
    // A button inside a form defaults to type="submit". A reveal toggle that posted the form
    // would be a data-loss bug reachable by one click, and no visual lane could see it.
    render(<Input type="password" aria-label="Password" defaultValue="" />);
    expect(screen.getByRole("button", { name: "Show password" })).toHaveAttribute("type", "button");
  });

  it("keeps Field's aria on the input, not on the wrapper", () => {
    // The one that would have shipped silently. `Field` clones its control to inject
    // `aria-describedby` and `aria-invalid`, and the sheet's invalid border is
    // `input[data-terp="input"][aria-invalid="true"]` — a single-element selector. If the spread
    // landed on the wrapper span, the attribute would sit on one element and the marker on
    // another, the selector would match neither, and every password field with a hint or an error
    // would quietly lose its red border. There is one such field in the example app today.
    render(
      <Field label="Password" hint="At least 16 characters" error="Too short">
        <Input type="password" defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Password");
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("data-terp", "input");
    const described = (input.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean);
    expect(described).toHaveLength(2);
    // And the wrapper carries none of it.
    const wrapper = input.parentElement!;
    expect(wrapper).toHaveAttribute("data-terp", "input-password");
    expect(wrapper).not.toHaveAttribute("aria-invalid");
    expect(wrapper).not.toHaveAttribute("aria-describedby");
  });

  it("is named by the label TEXT, so the toggle's own name cannot join it", () => {
    // `Field` wraps the control in a `<label>`, so the toggle is a label descendant, and a label
    // takes its name from everything inside it. Chromium duly computed "Password Show password"
    // for this input until `Field` started pointing `aria-labelledby` at the label's text span.
    //
    // WHAT THIS TEST CAN AND CANNOT SEE, because the first version of it was worthless: jsdom's
    // accessible-name implementation does NOT walk into a descendant's `aria-label`, so
    // `toHaveAccessibleName("Password")` passed here while the real browser disagreed. It asserted
    // the deviation, not the fix. So the wiring is what is pinned here — the attribute exists and
    // resolves to the label text — and the computed NAME is asserted in a real engine, in
    // apps/workbench/visual/computed.spec.ts against the admin-user-create specimen.
    render(
      <Field label="Password">
        <Input type="password" defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Password");
    expect(input.tagName).toBe("INPUT");
    const labelledBy = input.getAttribute("aria-labelledby");
    expect(labelledBy).not.toBeNull();
    expect(document.getElementById(labelledBy!)?.textContent).toBe("Password");
    // The toggle keeps its own name; asserting it were unlabelled would be the wrong fix.
    expect(screen.getByRole("button", { name: "Show password" })).toBeInTheDocument();
  });

  it("disables its toggle when the field itself is disabled or read-only", () => {
    // A field the caller switched off is switched off as a whole. Otherwise the value stays
    // unreachable while the control beside it still reveals it.
    const { rerender } = render(<Input type="password" aria-label="Password" disabled />);
    expect(screen.getByRole("button", { name: "Show password" })).toBeDisabled();
    rerender(<Input type="password" aria-label="Password" readOnly />);
    expect(screen.getByRole("button", { name: "Show password" })).toBeDisabled();
    rerender(<Input type="password" aria-label="Password" />);
    expect(screen.getByRole("button", { name: "Show password" })).toBeEnabled();
  });

  it("keeps a revealed password out of spellcheck, autocorrect and autocapitalisation", () => {
    // Revealing swaps the type to `text`, which in some engines makes the value a candidate for
    // all three — two of which would rewrite what the user typed.
    render(<Input type="password" aria-label="Password" defaultValue="" />);
    const input = screen.getByLabelText("Password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveAttribute("spellcheck", "false");
    expect(input).toHaveAttribute("autocorrect", "off");
    expect(input).toHaveAttribute("autocapitalize", "none");
  });
});
