// @vitest-environment jsdom
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ModuleNav } from "./ModuleNav";
import { UiTextProvider } from "./uiText";

afterEach(cleanup);

function renderWithRouter(initialPath: string) {
  const rootRoute = createRootRoute({
    component: () => (
      <>
        <ModuleNav
          items={[
            { label: "Overview", to: "/tickets" },
            { label: "Projects", to: "/tickets/projects" },
          ]}
        />
        <Outlet />
      </>
    ),
  });
  const overviewRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/tickets",
    component: () => <p>Overview page</p>,
  });
  const projectsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/tickets/projects",
    component: () => <p>Projects page</p>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([overviewRoute, projectsRoute]),
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });

  render(<RouterProvider router={router} />);
}

describe("ModuleNav", () => {
  it("renders exact-route links and marks the active route", async () => {
    renderWithRouter("/tickets/projects");

    await waitFor(() =>
      expect(screen.getByRole("navigation", { name: "Module navigation" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/tickets");
    expect(screen.getByRole("link", { name: "Projects" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("returns nothing for an empty tab list", () => {
    const rootRoute = createRootRoute({ component: () => <ModuleNav items={[]} /> });
    const router = createRouter({
      routeTree: rootRoute,
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });

    const { container } = render(<RouterProvider router={router} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("localises the navigation landmark label", async () => {
    const rootRoute = createRootRoute({
      component: () => (
        <UiTextProvider strings={{ moduleNavigationLabel: "Module navigatie" }}>
          <ModuleNav items={[{ label: "Overzicht", to: "/" }]} />
        </UiTextProvider>
      ),
    });
    const router = createRouter({
      routeTree: rootRoute,
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });

    render(<RouterProvider router={router} />);

    await waitFor(() =>
      expect(screen.getByRole("navigation", { name: "Module navigatie" })).toBeInTheDocument(),
    );
  });
});
