// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DetailList, Stack } from "./layout";

afterEach(cleanup);

describe("Stack", () => {
  it("names a column at the default gap, with no inline styling", () => {
    render(
      <Stack data-testid="stack">
        <span>a</span>
        <span>b</span>
      </Stack>,
    );
    const el = screen.getByTestId("stack");
    expect(el.tagName).toBe("DIV");
    expect(el).toHaveAttribute("data-direction", "column");
    expect(el).toHaveAttribute("data-gap", "2");
    expect(el).not.toHaveAttribute("data-wrap");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("renders the requested element and names direction, gap and wrap", () => {
    render(
      <Stack data-testid="row" as="section" direction="row" gap={4} wrap>
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("row");
    expect(el.tagName).toBe("SECTION");
    expect(el).toHaveAttribute("data-direction", "row");
    expect(el).toHaveAttribute("data-gap", "4");
    expect(el).toHaveAttribute("data-wrap", "true");
    expect(el.getAttribute("style")).toBeNull();
  });

  it("keeps alignment inline, because it is an open set of CSS keywords", () => {
    // align/justify accept any alignment keyword, so they cannot become a rule per value
    // without inventing a vocabulary CSS already has (ADR 0094). They stay inline, and
    // the geometry attributes stay attributes — the two halves of the same element.
    render(
      <Stack data-testid="aligned" align="center" justify="space-between">
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("aligned");
    expect(el.style.alignItems).toBe("center");
    expect(el.style.justifyContent).toBe("space-between");
    expect(el.style.display).toBe("");
  });

  it("works as a form (submit handler fires)", () => {
    let submitted = false;
    render(
      <Stack
        as="form"
        data-testid="form"
        onSubmit={(event) => {
          event.preventDefault();
          submitted = true;
        }}
      >
        <button type="submit">go</button>
      </Stack>,
    );
    screen.getByText("go").click();
    expect(submitted).toBe(true);
  });
});

describe("DetailList", () => {
  it("renders label/value pairs as a definition list", () => {
    render(
      <DetailList
        items={[
          { label: "Owner", value: "Ada" },
          { label: { id: "detail.purchased", message: "Purchased" }, value: "2023-01-01" },
        ]}
      />,
    );
    expect(screen.getByText(/Owner/).tagName).toBe("DT");
    expect(screen.getByText("Ada").tagName).toBe("DD");
    expect(screen.getByText(/Purchased/)).toBeInTheDocument();
  });
});
