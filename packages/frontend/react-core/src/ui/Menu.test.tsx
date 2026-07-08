// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Menu, MenuItem } from "./Menu";

const items = ["Archive", "Duplicate", "Delete"];

afterEach(cleanup);

describe("Menu", () => {
  it("opens, roves enabled items, selects and restores trigger focus", () => {
    const onDelete = vi.fn();
    render(
      <Menu trigger="⋯" triggerLabel="More actions">
        {({ close }) => (
          <>
            <MenuItem label="Archive" onSelect={() => {}} />
            <MenuItem label="Duplicate" disabled onSelect={() => {}} />
            <MenuItem label="Delete" destructive onSelect={() => { onDelete(); close(true); }} />
          </>
        )}
      </Menu>,
    );

    const trigger = screen.getByRole("button", { name: "More actions" });
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on Escape and outside click", () => {
    render(
      <Menu trigger="Open" triggerLabel="Actions">
        {() => items.map((item) => <MenuItem key={item} label={item} onSelect={() => {}} />)}
      </Menu>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
