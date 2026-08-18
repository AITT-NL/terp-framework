// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Breadcrumbs } from "./Breadcrumbs";

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
