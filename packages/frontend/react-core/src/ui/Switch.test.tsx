// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Switch } from "./Switch";

afterEach(cleanup);

describe("Switch", () => {
  it("renders an accessible switch and reports checked changes", () => {
    const onChange = vi.fn();
    render(<Switch label="Email alerts" checked={false} onChange={onChange} />);
    const toggle = screen.getByRole("switch", { name: "Email alerts" });
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
