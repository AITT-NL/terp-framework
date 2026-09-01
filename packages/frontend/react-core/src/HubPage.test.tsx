// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HubCard, HubPage } from "./HubPage";

afterEach(cleanup);

describe("HubPage", () => {
  it("renders the h1 title and a grid of cards", () => {
    render(
      <HubPage title="Administration">
        <HubCard to="/users" title="Users" description="Manage accounts" />
        <HubCard to="/roles" title="Roles" />
      </HubPage>,
    );

    const heading = screen.getByRole("heading", { level: 1, name: "Administration" });
    expect(heading).toBeInTheDocument();
    // A parentless hub is a trail of ONE, not a bare heading, so its title sits exactly where
    // an overview's and a detail's do and does not move when you descend. The trail is
    // therefore present and has nothing to link to yet.
    expect(heading).toHaveAttribute("data-terp", "page-title");
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getAllByText("Administration")).toHaveLength(1);
    // The marker, not the declaration. jsdom does not compute the cascade, so toHaveStyle
    // can only ever see an inline style — asserting gridAutoRows here was asserting that the
    // grid is styled from a style object, which is the thing ADR 0094 removes. What a test
    // should assert is the fact the sheet keys on; the geometry is gated by styles.test.ts
    // (the rule exists) and by the hub-page baselines (it does what it says).
    // getByRole("list") would be ambiguous now that the trail renders an <ol> of its own, and
    // the ambiguity is the assertion's own fault rather than the trail's: what it means is
    // "the grid is the marked element", so it asks for the grid.
    expect(
      screen.getAllByRole("list").find((list) => list.dataset.terp === "hubpage-grid"),
      "the card grid must be the marked list",
    ).toBeDefined();
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Roles/ })).toBeInTheDocument();
    expect(screen.getByText("Manage accounts")).toBeInTheDocument();
  });

  it("uses the normal breadcrumb frame when the hub is nested", () => {
    render(
      <HubPage title="Administration" parents={[{ label: "Home", to: "/" }]}>
        <HubCard to="/users" title="Users" />
      </HubPage>,
    );

    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent(
      "HomeAdministration",
    );
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });

  it("keeps the base Page breadcrumbs prop as a compatibility alias", () => {
    render(
      <HubPage title="Administration" breadcrumbs={[{ label: "Home", to: "/" }]}>
        <HubCard to="/users" title="Users" />
      </HubPage>,
    );
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });
});

describe("HubCard", () => {
  it("links the whole card to its destination by default", () => {
    render(
      <HubPage title="Hub">
        <HubCard to="/users" title="Users" />
      </HubPage>,
    );

    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/users");
  });

  it("renders through the supplied link renderer and shows the live stat", () => {
    render(
      <HubPage title="Hub">
        <HubCard
          to="/users"
          title="Users"
          stat={<span>142 active</span>}
          renderLink={({ to, children }) => (
            <a href={to} data-router="stack">
              {children}
            </a>
          )}
        />
      </HubPage>,
    );

    const link = screen.getByRole("link", { name: /Users/ });
    expect(link).toHaveAttribute("data-router", "stack");
    expect(screen.getByText("142 active")).toBeInTheDocument();
  });

  it("reserves the same internal tracks when optional card content is absent", () => {
    render(
      <HubPage title="Hub">
        <HubCard to="/short" title="Short" />
        <HubCard to="/full" title="Full" description="Description" stat="12" />
      </HubPage>,
    );

    const bodies = screen.getAllByText(/Short|Full/, { selector: "strong" }).map(
      (title) => title.closest('[data-terp="hubcard-body"]'),
    );
    expect(bodies).toHaveLength(2);
    // What this test can actually establish, and it is the load-bearing half: both rows are
    // PRESENT on the bare card, carrying a placeholder, so the body has three grid children
    // either way. The equal-height claim is the tracks rule plus these placeholders, and the
    // tracks rule is now in the sheet — gated by styles.test.ts for existence and by
    // hub-card-bare, whose whole subject is a bare card sitting flush with a full one.
    const shortBody = bodies[0]!;
    const fullBody = bodies[1]!;
    expect(shortBody.children).toHaveLength(fullBody.children.length);
    // And the attribute the rule reads. Asserting visibility: hidden here asserted an inline
    // style object; asserting data-empty asserts the fact, which is what survives the move.
    for (const part of ["hubcard-description", "hubcard-stat"] as const) {
      expect(shortBody.querySelector(`[data-terp="${part}"]`)).toHaveAttribute(
        "data-empty",
        "true",
      );
      expect(fullBody.querySelector(`[data-terp="${part}"]`)).not.toHaveAttribute("data-empty");
    }
  });
});
