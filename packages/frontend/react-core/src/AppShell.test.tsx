// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NavItem } from "@terp/contract";

import { AppShell, SIDEBAR_STORAGE_KEY } from "./AppShell";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const nav: NavItem[] = [
  { label: "Notes", to: "/notes", icon: "list" },
  { label: "Users", to: "/users", role: "admin" },
];

function renderShell(extra?: Partial<Parameters<typeof AppShell>[0]>) {
  return render(
    <AppShell
      title="Terp"
      nav={nav}
      renderLink={(item, children) => <a href={item.to}>{children}</a>}
      navFooter={<p>pinned footer</p>}
      {...extra}
    >
      <p>page content</p>
    </AppShell>,
  );
}

/** Make the shell believe it is below the mobile breakpoint. */
function stubMobileViewport() {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
}

describe("AppShell", () => {
  it("renders the landmarks, brand, footer, and the nav via renderLink", () => {
    renderShell();

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    // The brand (logo + title) lives in the sidebar; the default footer echoes the title.
    expect(screen.getAllByText("Terp").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/notes");
    expect(screen.getByText("page content")).toBeInTheDocument();
    // The navFooter slot renders inside the sidebar (pinned chrome, e.g. UserMenu).
    expect(screen.getByText("pinned footer")).toBeInTheDocument();
  });

  it("collapses to an icon rail and persists the choice", () => {
    renderShell({ navFooter: ({ collapsed }) => <p>{collapsed ? "rail" : "full"}</p> });

    expect(screen.getByText("full")).toBeInTheDocument();
    expect(screen.getByText("Notes")).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
    fireEvent.click(toggle);

    // Labels and the brand title leave the rail; icons (and the fallback tile) remain.
    expect(screen.queryByText("Notes")).not.toBeInTheDocument();
    expect(screen.getByText("U")).toBeInTheDocument(); // Users' fallback initial tile
    expect(screen.getByText("rail")).toBeInTheDocument();
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("restores the collapsed rail from localStorage", () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    renderShell();
    expect(screen.queryByText("Notes")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("renders a custom logo and footer in their slots", () => {
    renderShell({ logo: <span>MyMark</span>, footer: <span>v1.2.3</span> });
    expect(screen.getByText("MyMark")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("v1.2.3");
  });

  it("becomes an overlay drawer on mobile: opens from the header, closes on nav click", () => {
    stubMobileViewport();
    renderShell();

    // Closed drawer: no nav in the tree, only the header toggle.
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close navigation" })).toBeInTheDocument();

    // Choosing a destination closes the drawer.
    fireEvent.click(screen.getByRole("link", { name: "Notes" }));
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
  });

  it("closes the mobile drawer on Escape", () => {
    stubMobileViewport();
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
  });
});
