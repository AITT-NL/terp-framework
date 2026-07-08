// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PageActions } from "./PageActions";
import { Button } from "./ui/Button";
import { UiTextProvider } from "./uiText";

afterEach(cleanup);

describe("PageActions", () => {
  it("returns no wrapper when no actions are supplied", () => {
    const { container } = render(<PageActions />);

    expect(container).toBeEmptyDOMElement();
  });

  it("orders overflow, secondary, then primary actions", () => {
    render(
      <PageActions
        overflow={[{ label: "Archive", onSelect: () => {} }]}
        secondary={<Button variant="secondary">Filter</Button>}
        primary={<Button>Save</Button>}
      />,
    );

    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "⋯",
      "Filter",
      "Save",
    ]);
  });

  it("opens overflow actions and closes after selecting one, restoring trigger focus", () => {
    const onSelect = vi.fn();
    render(<PageActions overflow={[{ label: "Delete", variant: "destructive", onSelect }]} />);

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More actions" })).toHaveFocus();
  });

  it("moves focus into the menu on open and roams items with arrow keys", () => {
    render(
      <PageActions
        overflow={[
          { label: "Archive", onSelect: () => {} },
          { label: "Duplicate", onSelect: () => {}, disabled: true },
          { label: "Delete", onSelect: () => {} },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    const menu = screen.getByRole("menu");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Home" });
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "End" });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
  });

  it("closes on Escape (restoring trigger focus) and on outside click", () => {
    render(<PageActions overflow={[{ label: "Archive", onSelect: () => {} }]} />);

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More actions" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes when tabbing away from the menu", () => {
    render(<PageActions overflow={[{ label: "Archive", onSelect: () => {} }]} />);

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Tab" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("localises the overflow trigger label", () => {
    render(
      <UiTextProvider strings={{ moreActions: "Meer acties" }}>
        <PageActions overflow={[{ label: "Archiveren", onSelect: () => {} }]} />
      </UiTextProvider>,
    );

    expect(screen.getByRole("button", { name: "Meer acties" })).toBeInTheDocument();
  });
});
