// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "./Button";
import { Tooltip } from "./Tooltip";

afterEach(cleanup);

describe("Tooltip", () => {
  it("describes its trigger and opens on focus and hover", () => {
    render(
      <Tooltip content="More information">
        <Button>Help</Button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "Help" });
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(tooltip).not.toBeVisible();
    fireEvent.focus(trigger);
    expect(tooltip).toBeVisible();
    fireEvent.blur(trigger);
    expect(tooltip).not.toBeVisible();
    fireEvent.mouseEnter(trigger.parentElement!);
    expect(tooltip).toBeVisible();
  });
});
