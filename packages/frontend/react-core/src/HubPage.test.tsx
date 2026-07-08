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

    expect(screen.getByRole("heading", { level: 1, name: "Administration" })).toBeInTheDocument();
    // Two lists exist by construction: the breadcrumb trail and the card grid.
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    const grid = screen.getAllByRole("list").find((list) => !crumbs.contains(list));
    expect(grid).toBeDefined();
    expect(screen.getByRole("link", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Roles/ })).toBeInTheDocument();
    expect(screen.getByText("Manage accounts")).toBeInTheDocument();
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
});
