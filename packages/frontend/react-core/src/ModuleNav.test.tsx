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

    // The styling key is data-active, and the point is that it is NOT the aria-current beside
    // it: a router Link merges its own active props last, so that attribute has a second author.
    //
    // The divergence this comment used to describe is fixed (ADR 0097 §6, amended in 4e). Both
    // authors now compute the same thing by construction rather than by coincidence. The
    // component asks `activeNavPath` over the whole strip; the Link is pinned to
    // `exact: true, includeSearch: false`, so the router volunteers `aria-current` only when the
    // path equals the URL — the longest possible match, hence always the tab the predicate
    // picked. It can agree or stay silent; it cannot name a different tab. Which is why the
    // assertion below can now demand exactly one `aria-current` in the strip.
    const active = screen.getByRole("link", { name: "Projects" });
    const inactive = screen.getByRole("link", { name: "Overview" });
    expect(active).toHaveAttribute("data-terp", "module-nav-link");
    expect(active).toHaveAttribute("data-active", "true");
    expect(inactive).toHaveAttribute("data-terp", "module-nav-link");
    expect(inactive).not.toHaveAttribute("data-active");
    expect(active.getAttribute("style")).toBeNull();
    expect(inactive.getAttribute("style")).toBeNull();

    // Exactly one, over the whole strip. Before 4e the Link was left prefix-matching, so at
    // /tickets/projects the router added its own aria-current to the /tickets tab as well and a
    // screen reader announced two current pages.
    expect(
      document.querySelectorAll('[data-terp="module-nav"] [aria-current="page"]'),
    ).toHaveLength(1);
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
