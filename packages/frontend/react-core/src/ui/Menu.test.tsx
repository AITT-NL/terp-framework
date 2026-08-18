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
    const panel = menu.parentElement as HTMLElement;
    expect(panel).toHaveAttribute("data-terp", "popover-panel");
    // The panel's appearance is a sheet rule now (ADR 0094), so what it inlines is the whole
    // assertion — and it can be the whole assertion, because nothing can inject panel styles
    // any more: `panelStyle` went with UserMenu's migration. Exactly three declarations, the
    // measured ones.
    expect([...panel.style].sort()).toEqual(["left", "top", "visibility"]);
    expect(panel.style.top).not.toBe("");
    expect(panel.style.left).not.toBe("");
    // And the owner attribute, which is the only handle a rule has on a panel this component
    // portalled to document.body.
    expect(panel).toHaveAttribute("data-owner", "popover");
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
  it("returns focus to the trigger on Tab, so the tab order continues after the button", () => {
    render(
      <Menu trigger="Open" triggerLabel="Actions">
        {() => (
          <>
            <MenuItem label="Archive" onSelect={() => {}} />
            <MenuItem label="Delete" onSelect={() => {}} />
          </>
        )}
      </Menu>,
    );
    const trigger = screen.getByRole("button", { name: "Actions" });
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(menu.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(menu, { key: "Tab" });

    // The panel closes AND focus goes back to the trigger. Closing without restoring left focus
    // on a tabIndex=-1 item inside a panel portalled to the end of document.body, which is then
    // unmounted — so the browser's sequential-navigation starting point was a removed node at
    // the wrong end of the document and Tab landed past all page content. The APG menu-button
    // contract is that Tab moves to the next element after the BUTTON.
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
