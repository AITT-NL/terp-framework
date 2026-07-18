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
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Administration")).toHaveLength(1);
    expect(screen.getByRole("list")).toHaveStyle({ gridAutoRows: "1fr" });
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
    for (const body of bodies) {
      expect(body).toHaveStyle({
        gridTemplateRows: "auto minmax(3rem, 1fr) auto",
        minHeight: "10rem",
      });
    }
    const shortBody = bodies[0]!;
    expect(shortBody.querySelector('[data-terp="hubcard-description"]')).toHaveStyle({
      visibility: "hidden",
    });
    expect(shortBody.querySelector('[data-terp="hubcard-stat"]')).toHaveStyle({
      visibility: "hidden",
    });
  });
});
