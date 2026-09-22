// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TileGroup } from "./TileGroup";
import type { Tile } from "./TileGroup";

const TILES: Tile[] = [
  { value: "none", label: "No access" },
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Administrator", tone: "danger" },
];

function setup(overrides: Partial<Parameters<typeof TileGroup>[0]> = {}) {
  const onCommit = vi.fn();
  render(
    <TileGroup
      label="Access in this module"
      tiles={TILES}
      value="viewer"
      onCommit={onCommit}
      {...overrides}
    />,
  );
  return { onCommit };
}

afterEach(cleanup);

describe("TileGroup", () => {
  it("is a radiogroup whose whole set of choices is visible at once", () => {
    setup();
    // The reason this is not a Select: every option is present without opening anything, so two
    // of them can be compared. A dropdown hides that the choices exist at all.
    expect(screen.getByRole("radiogroup", { name: "Access in this module" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio").map((tile) => tile.textContent)).toEqual([
      "No access",
      "Viewer",
      "Editor",
      "Administrator",
    ]);
    expect(screen.getByRole("radio", { name: "Viewer" })).toHaveAttribute("aria-checked", "true");
  });

  it("moves focus on arrow without committing, and commits on Space", () => {
    // The load-bearing accessibility decision. A native radio group activates on arrow, and the
    // most privileged tile here sits behind a confirmation — so automatic activation would fire
    // that confirmation while someone was merely arrowing past it.
    const { onCommit } = setup();
    const viewer = screen.getByRole("radio", { name: "Viewer" });
    viewer.focus();

    fireEvent.keyDown(viewer, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Editor" })).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.keyDown(screen.getByRole("radio", { name: "Editor" }), { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Administrator" })).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.keyDown(screen.getByRole("radio", { name: "Administrator" }), { key: " " });
    expect(onCommit).toHaveBeenCalledExactlyOnceWith("admin");
  });

  it("commits on Enter as well, because both are confirm keys", () => {
    const { onCommit } = setup();
    const editor = screen.getByRole("radio", { name: "Editor" });
    editor.focus();
    fireEvent.keyDown(editor, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledExactlyOnceWith("editor");
  });

  it("wraps at the ends and jumps with Home/End", () => {
    // A strip is a closed set: arrowing off the end and stopping dead reads as a broken control
    // rather than as a boundary.
    setup();
    const first = screen.getByRole("radio", { name: "No access" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: "Administrator" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("radio", { name: "Administrator" }), { key: "Home" });
    expect(screen.getByRole("radio", { name: "No access" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("radio", { name: "No access" }), { key: "End" });
    expect(screen.getByRole("radio", { name: "Administrator" })).toHaveFocus();
  });

  it("keeps one tab stop, on the selection", () => {
    // The roving tabindex: Tab reaches the group once and the arrows move within it, which is
    // what a radiogroup is supposed to feel like. Four tab stops would make a strip of tiles
    // slower to pass than a dropdown.
    setup();
    const stops = screen
      .getAllByRole("radio")
      .filter((tile) => tile.getAttribute("tabindex") === "0");
    expect(stops.map((tile) => tile.textContent)).toEqual(["Viewer"]);
  });

  it("puts the tab stop on the first tile when nothing is selected", () => {
    // A group with no selection still has to be reachable by Tab, and the strip's leftmost
    // tile is where a reader expects to arrive — `No access` here, which is also the tile a
    // reader who wants to take a rung away is looking for.
    setup({ value: null });
    const stops = screen
      .getAllByRole("radio")
      .filter((tile) => tile.getAttribute("tabindex") === "0");
    expect(stops.map((tile) => tile.textContent)).toEqual(["No access"]);
  });

  it("commits nothing at all while the whole group is disabled", () => {
    const { onCommit } = setup({ disabled: true });
    const editor = screen.getByRole("radio", { name: "Editor" });
    fireEvent.click(editor);
    fireEvent.keyDown(editor, { key: "Enter" });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole("radiogroup")).toHaveAttribute("aria-disabled", "true");
  });

  it("marks a floor distinctly from a selection", () => {
    // Two different facts: what the caller picked, and what is in force anyway. A single visual
    // state would conflate them, and the reader would think their choice was the whole story.
    setup({ value: "viewer", floor: "editor" });
    const picked = screen.getByRole("radio", { name: "Viewer" });
    const inForce = screen.getByRole("radio", { name: "Editor" });

    expect(picked).toHaveAttribute("data-selected", "true");
    expect(picked).not.toHaveAttribute("data-floor");

    expect(inForce).toHaveAttribute("data-floor", "true");
    expect(inForce).toHaveAttribute("aria-checked", "false");
    // The assertion that makes this test about *distinctness* rather than about presence. Added
    // after a mutation that also stamped `data-selected` on the floor tile passed everything
    // above it: marking the floor and marking it differently are two claims, and only the
    // second is what stops a reader thinking the strip shows their own choice as in force.
    expect(inForce).not.toHaveAttribute("data-selected");
  });

  it("renders what a rung hands over inside its own tile", () => {
    // The delta belongs on the tile, not in a tooltip: choosing between rungs means comparing
    // what each one buys, and a comparison you have to hover to make is not one.
    setup({
      tiles: [
        { value: "viewer", label: "Viewer", body: <span>Bekijken: 12</span> },
        { value: "editor", label: "Editor", body: <span>Wijzigen: 4</span> },
      ],
    });
    expect(screen.getByText("Bekijken: 12")).toBeInTheDocument();
    expect(screen.getByText("Wijzigen: 4")).toBeInTheDocument();
  });

  it("is a plain labelled group with no selection semantics when read-only", () => {
    // A disabled radiogroup announces a set of radio buttons with none of them checked, which
    // tells a screen-reader user they failed to choose something on a screen where there is
    // nothing to choose. The description mode makes no such claim: the tiles are still there
    // to be compared, and none of them pretends to be a control.
    render(<TileGroup label="What each role may do" tiles={TILES} readOnly />);
    expect(screen.getByRole("group", { name: "What each role may do" })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("radio")).toEqual([]);
    // Every tile's content still reaches the reader — that is the whole point of the mode.
    expect(screen.getByText("Administrator")).toBeInTheDocument();
  });

  it("carries no tab stop at all when read-only", () => {
    // The counterpart claim: nothing here is a control, so nothing here is in the tab order.
    // A roving tab stop over five unselectable tiles is five keystrokes that do nothing.
    const { container } = render(
      <TileGroup label="What each role may do" tiles={TILES} readOnly />,
    );
    expect(container.querySelectorAll("[tabindex]")).toHaveLength(0);
  });

  it("still marks the destructive rung when read-only, because the tone is the warning", () => {
    render(<TileGroup label="What each role may do" tiles={TILES} readOnly />);
    const tiles = [...document.querySelectorAll('[data-terp="tile"]')];
    expect(tiles.map((tile) => tile.getAttribute("data-tone"))).toEqual([
      null,
      null,
      null,
      "danger",
    ]);
  });
});
