// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Menu, MenuItem } from "./Menu";

const items = ["Archive", "Duplicate", "Delete"];

afterEach(cleanup);

describe("Menu", () => {
  it("portals the panel outside clipping ancestors without treating panel clicks as outside", () => {
    render(
      <div data-testid="clip" style={{ overflow: "hidden" }}>
        <Menu trigger="Open" triggerLabel="Actions">
          {({ close }) => <MenuItem label="Archive" onSelect={() => close()} />}
        </Menu>
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    const menu = screen.getByRole("menu");
    expect(screen.getByTestId("clip")).not.toContainElement(menu);
    expect(menu.parentElement).toHaveStyle({
      fontFamily: "var(--font-family-sans)",
      color: "var(--color-neutral-900)",
    });
    fireEvent.pointerDown(menu);
    expect(menu).toBeInTheDocument();
  });

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

  it("reports one controlled close for one outside pointer interaction", () => {
    const onOpenChange = vi.fn();
    render(
      <Menu trigger="Open" triggerLabel="Actions" open onOpenChange={onOpenChange}>
        {() => <MenuItem label="Archive" onSelect={() => {}} />}
      </Menu>,
    );

    fireEvent.pointerDown(document.body);
    expect(onOpenChange).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
