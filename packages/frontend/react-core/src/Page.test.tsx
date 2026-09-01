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

    const title = screen.getByRole("heading", { level: 1, name: "Tasks" });
    expect(title).toBeInTheDocument();
    // The marker, not the declaration. jsdom computes no cascade, so toHaveStyle could only
    // ever see an inline style — asserting the title's font size was asserting that Page
    // styles itself from a style object, which is the thing ADR 0094 removes. What a unit
    // test can hold is the fact the sheet keys on; the type is gated by styles.test.ts for
    // existence and by the page-header baseline for what it renders as.
    expect(title).toHaveAttribute("data-terp", "page-title");
    expect(title.getAttribute("style")).toBeNull();
    expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument();
    const action = screen.getByRole("button", { name: "New" });
    expect(title.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("renders a parentless page as a trail of one, in the same boxes as a deeper page", () => {
    // The overview and the detail have to put the title in the SAME place, or the name moves
    // the moment you open a record. So a parentless page is a trail of one rather than a bare
    // heading: same nav, same list, same leaf, no ancestors in front of it yet.
    const root = render(<Page title="Tasks">x</Page>);
    const rootLeaf = screen.getByRole("heading", { level: 1, name: "Tasks" });
    expect(rootLeaf).toHaveAttribute("data-terp", "page-title");
    // Still exactly once: the leaf IS the heading, so there is nothing to repeat.
    expect(screen.getAllByText("Tasks")).toHaveLength(1);
    // The ancestry of the heading is the shape that must not differ between the two.
    const chain = (node: HTMLElement) => {
      const tags: string[] = [];
      for (let at = node.parentElement; at !== null; at = at.parentElement) {
        tags.push(at.tagName);
        if (at.dataset.terp === "page-heading") break;
      }
      return tags;
    };
    const rootChain = chain(rootLeaf);
    expect(rootChain).toEqual(["LI", "OL", "NAV", "DIV"]);
    root.unmount();

    const deep = render(
      <Page title="Fix the door" breadcrumbs={[{ label: "Tasks", to: "/tasks" }]}>
        x
      </Page>,
    );
    expect(chain(screen.getByRole("heading", { level: 1, name: "Fix the door" }))).toEqual(
      rootChain,
    );
    deep.unmount();
  });

  it("appends its own crumb to the supplied trail", () => {
    render(
      <Page title="Fix the door" breadcrumbs={[{ label: "Tasks", to: "/tasks" }]}>
        x
      </Page>,
    );

    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/tasks");
    // The leaf of the trail IS the h1 now, so the page's name appears ONCE. It used to
    // appear twice: Page built its trail as [...breadcrumbs, { label: title }] and then
    // rendered <h1>{title}</h1>, so every DetailPage printed its own name as the leaf crumb
    // and again a couple of dozen pixels below it. That duplication was the whole reason the
    // header collapsed into one band, and this is the assertion that holds it.
    const heading = screen.getByRole("heading", { level: 1, name: "Fix the door" });
    expect(heading).toHaveAttribute("aria-current", "page");
    expect(heading).toHaveAttribute("data-terp", "page-title");
    expect(screen.getAllByText("Fix the door")).toHaveLength(1);
  });

  it("renders badges and a lead line on the band, and neither when absent", () => {
    const { container, unmount } = render(
      <Page title="Fix the door" badges={<span>Open</span>} description="Reported yesterday">
        x
      </Page>,
    );

    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Reported yesterday")).toBeInTheDocument();
    expect(container.querySelector('[data-terp="page-badges"]')).not.toBeNull();
    expect(container.querySelector('[data-terp="page-description"]')).not.toBeNull();
    unmount();

    // Absent is not an empty row: a band that reserved space for slots no page filled would
    // put a gap next to every title in every app that passes neither.
    const bare = render(<Page title="Fix the door">x</Page>);
    expect(bare.container.querySelector('[data-terp="page-badges"]')).toBeNull();
    expect(bare.container.querySelector('[data-terp="page-description"]')).toBeNull();
  });

  it("takes several badges as one row, not one row each", () => {
    const { container } = render(
      <Page title="Fix the door" badges={[<span key="a">Open</span>, <span key="b">Urgent</span>]}>
        x
      </Page>,
    );

    expect(container.querySelectorAll('[data-terp="page-badges"]')).toHaveLength(1);
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Urgent")).toBeInTheDocument();
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
  it("puts its title where a detail page puts its own: the trail's leaf", () => {
    render(<OverviewPage title="Tasks">list</OverviewPage>);

    const leaf = screen.getByRole("heading", { level: 1, name: "Tasks" });
    expect(leaf).toHaveAttribute("data-terp", "page-title");
    expect(leaf).toHaveAttribute("aria-current", "page");
    // A trail of one has no ancestors to link to, which is the whole difference between an
    // overview and the detail beneath it.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
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
    const leaf = screen.getByRole("heading", { level: 1, name: "Fix the door" });
    expect(screen.getAllByText("Fix the door")).toHaveLength(1);
    expect(leaf).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("detail")).toBeInTheDocument();
  });
});
