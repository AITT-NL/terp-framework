// @vitest-environment jsdom
//
// What each hand-roll of this control had to get right on its own: the button says whether
// it is open, names the region it controls, and that region exists to be named. Those three
// are the whole reason a component is worth more here than a `<details>` recipe, so they are
// what these tests hold.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Disclosure } from "./Disclosure";

afterEach(cleanup);

describe("Disclosure", () => {
  it("wires the toggle to the region it reveals", () => {
    render(
      <Disclosure label="Technical details">
        <p>the payload</p>
      </Disclosure>,
    );
    const toggle = screen.getByRole("button", { name: "Technical details" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByText("the payload").closest("[data-terp='disclosure-panel']");
    // The join a hand-roll forgets: without it a screen reader reaches the button and has
    // no way to find what it opened.
    expect(toggle.getAttribute("aria-controls")).toBe(panel?.getAttribute("id"));
  });

  it("does not render the panel while closed", () => {
    // Unmounted, not hidden. Hidden content stays in the accessibility tree unless every
    // branch remembers `hidden`, and it keeps doing whatever it renders — a disclosure over
    // a live log then costs its work on every screen that has one, for a region nobody
    // opened.
    render(
      <Disclosure label="Technical details">
        <p>the payload</p>
      </Disclosure>,
    );

    expect(screen.queryByText("the payload")).toBeNull();
  });

  it("opens on first render when asked", () => {
    render(
      <Disclosure label="Technical details" defaultOpen>
        <p>the payload</p>
      </Disclosure>,
    );

    expect(screen.getByText("the payload")).toBeTruthy();
  });

  it("lets the caller own the state", () => {
    const onOpenChange = vi.fn();
    render(
      <Disclosure label="Technical details" open={false} onOpenChange={onOpenChange}>
        <p>the payload</p>
      </Disclosure>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Technical details" }));

    // Reported, not applied: a controlled disclosure shows what the prop says, which is the
    // same invariant the controlled Combobox keeps.
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.queryByText("the payload")).toBeNull();
  });

  it("gives two disclosures on one screen different region ids", () => {
    // `useId` rather than a module counter: two instances sharing an id would point every
    // `aria-controls` at the first panel, and the second control would silently describe
    // somebody else's content.
    render(
      <>
        <Disclosure label="First" defaultOpen>
          <p>one</p>
        </Disclosure>
        <Disclosure label="Second" defaultOpen>
          <p>two</p>
        </Disclosure>
      </>,
    );

    const [first, second] = screen.getAllByRole("button");
    expect(first.getAttribute("aria-controls")).not.toBe(second.getAttribute("aria-controls"));
  });

  it("marks itself open so the stylesheet can reach the state", () => {
    const { container } = render(
      <Disclosure label="Technical details">
        <p>the payload</p>
      </Disclosure>,
    );
    const root = container.querySelector("[data-terp='disclosure']");
    expect(root?.hasAttribute("data-open")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Technical details" }));

    expect(root?.hasAttribute("data-open")).toBe(true);
  });
});
