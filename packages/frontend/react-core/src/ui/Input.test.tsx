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

  it("reveals and re-hides the value, and says which it will do", () => {
    render(<Input type="password" aria-label="Password" defaultValue="hunter2" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    // The name follows the state: pressed, and now offering the opposite action.
    const pressed = screen.getByRole("button", { name: "Hide password" });
    expect(pressed).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(pressed);
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

  it("does not lend its toggle's name to the field it sits in", () => {
    // `Field` wraps the control in a `<label>`, so the toggle is a label descendant. If the
    // button contributed to the label's text, the input would be called "Password Show password"
    // and a voice-control user would have to say a sentence that is nowhere on screen.
    render(
      <Field label="Password">
        <Input type="password" defaultValue="" />
      </Field>,
    );
    const input = screen.getByLabelText("Password");
    expect(input.tagName).toBe("INPUT");
    // Exactly "Password", not "Password Show password". The toggle keeps its own name — asserting
    // the toggle is unlabelled would be the wrong fix and this test would then pass for the wrong
    // reason, so what is pinned is the INPUT's name being unaffected by a sibling that has one.
    expect(input).toHaveAccessibleName("Password");
    expect(screen.getByRole("button", { name: "Show password" })).toBeInTheDocument();
  });
});
