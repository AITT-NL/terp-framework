// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReactNode } from "react";

import { Breadcrumbs } from "./Breadcrumbs";
import { TrailMemoryContext, trailMemory } from "./trailMemory";

afterEach(cleanup);

describe("Breadcrumbs", () => {
  it("renders a Breadcrumb landmark with ancestor links and the current page marked", () => {
    render(
      <Breadcrumbs
        items={[
          { label: "Tasks", to: "/tasks" },
          { label: "Fix the door" },
        ]}
      />,
    );

    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
    expect(screen.getByText("Fix the door")).toHaveAttribute("aria-current", "page");
  });

  it("uses renderLink for ancestor crumbs (router-agnostic)", () => {
    render(
      <Breadcrumbs
        items={[
          { label: "Tasks", to: "/tasks" },
          { label: "Detail" },
        ]}
        renderLink={(item) => <a href={`#${item.to}`}>{item.label}</a>}
      />,
    );

    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "#/tasks");
  });

  it("renders an ancestor without a `to` as plain text (never a dead link)", () => {
    render(<Breadcrumbs items={[{ label: "Section" }, { label: "Here" }]} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Section")).not.toHaveAttribute("aria-current");
  });

  it("renders the current crumb as the page heading when asked, and only then", () => {
    // The page band's case: the trail IS the title, so its leaf is the view's single h1
    // rather than a second copy of the same string sitting under the trail. The element
    // changes and the accessible current-ness does not.
    const { container } = render(
      <Breadcrumbs
        items={[{ label: "Tasks", to: "/tasks" }, { label: "Fix the door" }]}
        currentAs="h1"
      />,
    );

    const heading = screen.getByRole("heading", { level: 1, name: "Fix the door" });
    expect(heading).toHaveAttribute("aria-current", "page");
    // The marker moves with the element, because the two mean different things to the sheet:
    // a trail's end, versus a heading that happens to sit at the trail's end.
    expect(heading).toHaveAttribute("data-terp", "page-title");
    expect(container.querySelector('[data-terp="breadcrumbs-current"]')).toBeNull();
    // The ancestor is untouched: currentAs describes the LEAF only.
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
  });

  it("defaults to a span, so a standalone trail mints no heading", () => {
    // The default matters as much as the option. A wayfinding trail rendered anywhere on a
    // page must not introduce an h1 competing with that page's own.
    render(<Breadcrumbs items={[{ label: "Tasks", to: "/tasks" }, { label: "Here" }]} />);

    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByText("Here")).toHaveAttribute("data-terp", "breadcrumbs-current");
  });

  it("marks only the final crumb as current, on a marker of its own", () => {
    // The current-crumb styling deliberately does NOT key on aria-current. A router's Link
    // stamps aria-current="page" on every link whose path is a prefix of the current one —
    // which every ancestor crumb is — so borrowing that attribute painted the whole trail as
    // the current page. The marker says what this component means, not what a router infers.
    const { container } = render(
      <Breadcrumbs
        items={[{ label: "Tasks", to: "/tasks" }, { label: "Open", to: "/tasks/open" }, { label: "Here" }]}
        renderLink={(item) => (
          <a href={item.to} aria-current="page">
            {item.label}
          </a>
        )}
      />,
    );

    const current = container.querySelectorAll('[data-terp="breadcrumbs-current"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Here");
    // Both ancestors claim aria-current here, which is exactly the router behaviour that
    // made the old selector wrong — and none of them may pick up the current styling.
    expect(container.querySelectorAll('[aria-current="page"]')).toHaveLength(3);
  });
});

// A trail that keeps what it knows (ADR 0173): a label not known yet is never a stand-in, the
// trail recalls what it said at a path before, and a crumb is updated in place rather than
// replaced, so going deeper only adds a crumb.
describe("a trail that keeps what it knows", () => {
  function within(pathname: string, labels: Map<string, string>, node: ReactNode) {
    return (
      <TrailMemoryContext.Provider value={trailMemory(labels, pathname)}>{node}</TrailMemoryContext.Provider>
    );
  }

  it("shows a placeholder, read as loading, for a leaf never seen before", () => {
    render(<Breadcrumbs items={[{ label: "Users", to: "/users" }, { label: null }]} currentAs="h1" />);
    const heading = screen.getByRole("heading", { level: 1 });
    // Mutation: the parent's name as the stand-in, which is a wrong title for as long as it shows.
    expect(heading).toHaveTextContent("Loading...");
    expect(heading).not.toHaveTextContent("Users");
    expect(heading).toHaveAttribute("aria-busy", "true");
    expect(heading.querySelector('[data-terp="breadcrumbs-pending"]')).not.toBeNull();
  });

  it("recalls the leaf's last label at its path while the page reloads it", () => {
    const labels = new Map<string, string>();
    const { rerender } = render(within("/users/u1", labels, <Breadcrumbs items={[{ label: "Jane" }]} />));
    // The same place, mounted again (a tab of the detail, or coming back): its record loads again.
    rerender(within("/users/u1/", labels, <Breadcrumbs items={[{ label: "" }]} />));
    expect(screen.getByText("Jane")).toHaveAttribute("aria-current", "page");
    expect(document.querySelector('[data-terp="breadcrumbs-pending"]')).toBeNull();
  });

  it("recalls a parent one level down, where only the child page has loaded", () => {
    const labels = new Map([["/users/u1", "Jane"]]);
    render(
      within(
        "/users/u1/history",
        labels,
        <Breadcrumbs
          items={[{ label: "Users", to: "/users" }, { label: null, to: "/users/u1?tab=a" }, { label: "History" }]}
        />,
      ),
    );
    // Mutation: a pending ancestor looked up by its raw `to`, query and all.
    expect(screen.getByRole("link", { name: "Jane" })).toHaveAttribute("href", "/users/u1?tab=a");
  });

  it("does not remember one place's label for another", () => {
    const labels = new Map<string, string>();
    const { rerender } = render(within("/users/u1", labels, <Breadcrumbs items={[{ label: "Jane" }]} />));
    rerender(within("/users/u2", labels, <Breadcrumbs items={[{ label: null }]} />));
    expect(screen.queryByText("Jane")).toBeNull();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("updates a crumb in place when its label arrives", () => {
    const { rerender } = render(<Breadcrumbs items={[{ label: "Users", to: "/users" }, { label: null }]} />);
    const [, leaf] = screen.getAllByRole("listitem");
    rerender(<Breadcrumbs items={[{ label: "Users", to: "/users" }, { label: "Jane" }]} />);
    // Mutation: keyed by its text, which replaced the crumb when the words arrived.
    expect(screen.getAllByRole("listitem")[1]).toBe(leaf);
    expect(leaf).toHaveTextContent("Jane");
  });

  it("only adds a crumb when the trail goes one level deeper", () => {
    const { rerender } = render(<Breadcrumbs items={[{ label: "Users", to: "/users" }, { label: "Jane" }]} />);
    const [root, jane] = screen.getAllByRole("listitem");
    rerender(
      <Breadcrumbs items={[{ label: "Users", to: "/users" }, { label: "Jane", to: "/users/u1" }, { label: "History" }]} />,
    );
    const after = screen.getAllByRole("listitem");
    expect(after).toHaveLength(3);
    expect(after[0]).toBe(root);
    expect(after[1]).toBe(jane);
    expect(screen.getByRole("link", { name: "Jane" })).toHaveAttribute("href", "/users/u1");
  });
});
