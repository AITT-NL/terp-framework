// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Tabs } from "./Tabs";

const tabs = [
  { value: "overview", label: "Overview", content: <p>Overview panel</p> },
  { value: "audit", label: "Audit", content: <p>Audit panel</p> },
];

afterEach(cleanup);

describe("Tabs", () => {
  it("renders tabs and switches uncontrolled selection by click", () => {
    render(<Tabs label="Sections" tabs={tabs} defaultValue="overview" />);
    expect(screen.getByRole("tablist", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Overview panel");
    fireEvent.click(screen.getByRole("tab", { name: "Audit" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Audit panel");
  });

  it("reports controlled changes and supports arrow navigation", () => {
    const onChange = vi.fn();
    render(<Tabs label="Sections" tabs={tabs} value="overview" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("audit");
  });
});

describe("Tabs with a single tab", () => {
  it("renders the content bare, with no tablist to choose from", () => {
    // A tab set over one tab costs a row of the screen to offer nothing, and to a screen
    // reader it is worse than decorative: it announces "tab 1 of 1" and the only
    // affordance is already selected.
    render(<Tabs label="Sections" tabs={[{ value: "only", label: "Only", content: "Body" }]} />);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();
    // The panel goes too: a tabpanel exists to be labelled by the tab that reveals it, and
    // there is nothing left to reveal.
    expect(screen.queryByRole("tabpanel")).toBeNull();
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("keeps the chrome when that single tab is disabled", () => {
    // Here the tab set carries real information — this section exists and is unavailable —
    // and rendering its content bare would show what the caller marked unreachable.
    render(
      <Tabs
        label="Sections"
        tabs={[{ value: "only", label: "Only", content: "Body", disabled: true }]}
      />,
    );
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Only" })).toBeDisabled();
  });
});

describe("Tabs on a strip too narrow for them", () => {
  // jsdom lays nothing out, so the boxes are given: the strip is 100 to 300, and whichever tab
  // is selected sits where each test puts it.
  function boxes(selected: [number, number]) {
    return vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        const at = (left: number, right: number) =>
          ({ left, right, top: 0, bottom: 20, width: right - left, height: 20, x: left, y: 0 }) as DOMRect;
        if (this.dataset.terp === "tab-list") return at(100, 300);
        if (this.getAttribute("aria-selected") === "true") return at(...selected);
        return at(0, 0);
      });
  }

  it("scrolls the strip forward to a selected tab past its end, and follows the selection", () => {
    const spy = boxes([320, 360]);
    try {
      render(<Tabs label="Sections" tabs={tabs} defaultValue="audit" />);
      const list = screen.getByRole("tablist");
      // Mutation: no scroll, which leaves the selected tab out of sight on a phone.
      expect(list.scrollLeft).toBe(60);
      fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
      // Mutation: scrolling on mount only, not as the selection moves.
      expect(list.scrollLeft).toBe(120);
    } finally {
      spy.mockRestore();
    }
  });

  it("scrolls it back to a selected tab before its start", () => {
    // jsdom keeps a negative scroll position where a browser clamps it, which is what makes the
    // backward step visible here.
    const spy = boxes([60, 90]);
    try {
      render(<Tabs label="Sections" tabs={tabs} defaultValue="audit" />);
      // Mutation: scrolling only forwards, which leaves a tab before the strip's start hidden.
      expect(screen.getByRole("tablist").scrollLeft).toBe(-40);
    } finally {
      spy.mockRestore();
    }
  });
});
