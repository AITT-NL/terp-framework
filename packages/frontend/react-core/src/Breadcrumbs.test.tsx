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
});
