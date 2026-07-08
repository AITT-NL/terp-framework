// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RadioGroup } from "./Radio";

afterEach(cleanup);

describe("RadioGroup", () => {
  it("renders an accessible group and reports selected values", () => {
    const onChange = vi.fn();
    render(
      <RadioGroup
        label="Status"
        name="status"
        value="open"
        onChange={onChange}
        options={[
          { value: "open", label: "Open" },
          { value: "closed", label: "Closed" },
        ]}
      />,
    );
    expect(screen.getByRole("group", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Open" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Closed" }));
    expect(onChange).toHaveBeenCalledWith("closed");
  });
});
