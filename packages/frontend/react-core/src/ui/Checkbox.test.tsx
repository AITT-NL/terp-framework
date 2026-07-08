// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox } from "./Checkbox";

afterEach(cleanup);

describe("Checkbox", () => {
  it("renders a labelled checkbox and reports checked changes", () => {
    const onChange = vi.fn();
    render(<Checkbox label="Accept terms" checked={false} onChange={onChange} />);
    const checkbox = screen.getByRole("checkbox", { name: "Accept terms" });
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
