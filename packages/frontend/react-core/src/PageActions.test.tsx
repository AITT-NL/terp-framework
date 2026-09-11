// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PageActions } from "./PageActions";
import { Button } from "./ui/Button";
import { UiTextProvider } from "./uiText";

afterEach(cleanup);

/**
 * Put the cluster in one of its three regions.
 *
 * `readDensity` asks NARROW first and MEDIUM second, so the stub answers per query rather than
 * with one boolean: a width in the middle region matches MEDIUM and not NARROW, and that pair
 * is the only thing separating icons from a menu.
 */
function stubRegion(region: "narrow" | "medium" | "roomy") {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches:
        query === "(max-width: 768px)"
          ? region === "narrow"
          : query === "(max-width: 1024px)"
            ? region !== "roomy"
            : false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

// A text-free icon on purpose: the icon-only assertion below is that the BOX carries no
// text, and a glyph that is itself text would satisfy it for the wrong reason.
const SUPPORTING = [
  { label: "Discard", icon: <svg aria-hidden="true" focusable={false} />, onSelect: () => {} },
];

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
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes when tabbing away from the menu", () => {
    render(<PageActions overflow={[{ label: "Archive", onSelect: () => {} }]} />);

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Tab" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("shows supporting actions as labelled buttons above the second cutover", () => {
    stubRegion("roomy");
    render(<PageActions primary={<Button>Publish</Button>} secondaryActions={SUPPORTING} />);
    expect(screen.getByRole("button", { name: "Discard" })).toHaveTextContent("Discard");
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
  });

  it("drops supporting actions to icons alone in the middle region, keeping their names", () => {
    stubRegion("medium");
    render(<PageActions primary={<Button>Publish</Button>} secondaryActions={SUPPORTING} />);
    const discard = screen.getByRole("button", { name: "Discard" });
    // The label moves to the accessible name rather than being dropped: the control has to
    // read the same to a screen reader at every width, which is the whole cost of an icon.
    expect(discard).toHaveTextContent("");
    expect(discard).toHaveAttribute("title", "Discard");
    // Still a button, not a menu — the fold happens at the FIRST cutover, not this one.
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
  });

  it("folds supporting actions into the menu below the first cutover", () => {
    stubRegion("narrow");
    render(
      <PageActions
        primary={<Button>Publish</Button>}
        secondaryActions={SUPPORTING}
        overflow={[{ label: "Delete", variant: "destructive", onSelect: () => {} }]}
      />,
    );
    // Gone from the band...
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
    // ...and present in the menu, above the page's own rare items.
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    const items = screen.getAllByRole("menuitem").map((item) => item.textContent);
    expect(items).toEqual(["Discard", "Delete"]);
  });

  it("keeps the primary action labelled at every width", () => {
    // The decision ADR 0135 records: everything around the primary gives way, the primary
    // never does. Asserted in the narrowest region, where the pressure to fold it is highest.
    stubRegion("narrow");
    render(<PageActions primary={<Button>Publish</Button>} secondaryActions={SUPPORTING} />);
    expect(screen.getByRole("button", { name: "Publish" })).toHaveTextContent("Publish");
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
