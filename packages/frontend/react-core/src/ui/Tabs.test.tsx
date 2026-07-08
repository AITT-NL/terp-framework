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
