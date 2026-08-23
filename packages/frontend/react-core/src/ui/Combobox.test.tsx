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

  it("matches a needle that the host's own case fold would have hidden", () => {
    // The filter used to fold with `toLocaleLowerCase`, which asks the host what lowercase means.
    // Turkish has two i's, and folded there `Italy` becomes `ıtaly` — dotless — which does not
    // contain the `i` the user typed. Every option with a capital I disappeared for a Turkish
    // visitor and for nobody else, and folding BOTH sides the same way does not help: the needle
    // comes from a keyboard and the haystack from a server.
    //
    // The host is simulated rather than assumed, because the suite runs on nl-NL and a test that
    // merely typed `i` would pass under the bug here and fail only in Istanbul. The prototype
    // patch is scoped to this test and restored in `finally`.
    const original = String.prototype.toLocaleLowerCase;
    // Confirm the hazard is real on this ICU build before relying on it as the mechanism.
    expect(original.call("Italy", "tr")).not.toContain("i");
    String.prototype.toLocaleLowerCase = function turkish(this: string) {
      return original.call(this, "tr");
    };
    try {
      render(
        <Combobox
          aria-label="Country"
          options={[...options, { value: "it", label: "Italy" }]}
          onChange={vi.fn()}
        />,
      );
      const input = screen.getByRole("combobox", { name: /Country/ });
      fireEvent.focus(input);
      // BOTH cases, because each catches a different half and neither catches the other.
      //
      // Lowercase is the real defect: the user types the dotted `i` their keyboard produces,
      // Turkish folds the label to the dotless `ıtaly`, and the option vanishes. The ORIGINAL
      // code folded both sides with the host locale, which is self-consistent — "ıtal" does
      // occur in "ıtaly" — so a capital-I needle passes under the very bug this test exists
      // for. The first version of this test asserted only the capital, and was green against
      // it.
      //
      // Capital is still needed: it is the only case that fails when the NEEDLE alone reverts
      // to the host fold, which lowercase cannot see because folding "ital" changes nothing.
      for (const needle of ["ital", "Ital"]) {
        fireEvent.change(input, { target: { value: needle } });
        expect(
          screen.getByRole("option", { name: "Italy" }),
          `typing ${needle} must still match Italy on a Turkish host`,
        ).toBeInTheDocument();
      }
    } finally {
      String.prototype.toLocaleLowerCase = original;
    }
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

  it("opens on mount with the cursor on the selection when asked", () => {
    // The prop exists so the listbox can be rendered deterministically — it had no way in
    // at all before, which is why sixteen sheet rules for this subtree went unpainted by
    // both visual lanes from the moment they were written.
    render(<Combobox aria-label="Country" value="be" options={options} defaultOpen />);
    const listbox = screen.getByRole("listbox");
    expect(listbox).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "true");
    // The cursor lands on the selection rather than nowhere: an open list with no active
    // option is a state focusing the box never produces.
    const active = listbox.querySelector('[data-active="true"]');
    expect(active?.textContent).toBe("Belgium");
    expect(active).toHaveAttribute("aria-selected", "true");
  });

  it("keeps the listbox shut when disabled, even with defaultOpen", () => {
    render(
      <Combobox aria-label="Country" value="be" options={options} defaultOpen disabled />,
    );
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
