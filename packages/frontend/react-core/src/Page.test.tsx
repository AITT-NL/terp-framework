// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DetailPage } from "./DetailPage";
import { OverviewPage } from "./OverviewPage";
import { Page } from "./Page";
import { ApiError } from "./unwrap";
import { Button } from "./ui/Button";

afterEach(cleanup);

describe("Page", () => {
  it("renders the h1 title, the actions slot, and the body", () => {
    render(
      <Page title="Tasks" actions={<Button>New</Button>}>
        <p>body</p>
      </Page>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("does not repeat a root page title as a current-page-only breadcrumb", () => {
    render(<Page title="Tasks">x</Page>);

    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Tasks")).toHaveLength(1);
  });

  it("appends its own crumb to the supplied trail", () => {
    render(
      <Page title="Fix the door" breadcrumbs={[{ label: "Tasks", to: "/tasks" }]}>
        x
      </Page>,
    );

    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
    expect(screen.getByText("Fix the door", { selector: "span" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("replaces the body with the loading state while keeping the header", () => {
    render(
      <Page title="Tasks" isLoading>
        <p>body</p>
      </Page>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("body")).not.toBeInTheDocument();
  });

  it("surfaces an error instead of the body, winning over isLoading", () => {
    render(
      <Page title="Tasks" isLoading error="Not found">
        <p>body</p>
      </Page>,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong.");
    expect(alert).toHaveTextContent("Not found");
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    expect(screen.queryByText("body")).not.toBeInTheDocument();
  });

  it("maps a caught ApiError's stable code to the registered copy", () => {
    render(
      <Page
        title="Tasks"
        error={new ApiError("row was updated concurrently", { code: "stale_data", status: 409 })}
      >
        <p>body</p>
      </Page>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This item was changed by someone else. Refresh and try again.",
    );
    expect(screen.queryByText("row was updated concurrently")).not.toBeInTheDocument();
  });

  it("renders the custom loading and error slots when supplied", () => {
    const { rerender } = render(
      <Page title="Tasks" isLoading loadingState={<p>spinner</p>}>
        body
      </Page>,
    );
    expect(screen.getByText("spinner")).toBeInTheDocument();

    rerender(
      <Page title="Tasks" error="boom" errorState={<p>custom error</p>}>
        body
      </Page>,
    );
    expect(screen.getByText("custom error")).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });
});

describe("OverviewPage", () => {
  it("is a root-level Page with one title and no redundant breadcrumb", () => {
    render(<OverviewPage title="Tasks">list</OverviewPage>);

    expect(screen.getByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Tasks")).toHaveLength(1);
    expect(screen.getByText("list")).toBeInTheDocument();
  });
});

describe("DetailPage", () => {
  it("always breadcrumbs back to its parents, ending on the record's crumb", () => {
    render(
      <DetailPage
        title="Fix the door"
        parents={[{ label: "Tasks", to: "/tasks" }]}
        renderLink={(item) => <a href={item.to}>{item.label}</a>}
      >
        detail
      </DetailPage>,
    );

    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
    expect(screen.getByRole("heading", { level: 1, name: "Fix the door" })).toBeInTheDocument();
    expect(screen.getByText("Fix the door", { selector: "span" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("detail")).toBeInTheDocument();
  });
});
