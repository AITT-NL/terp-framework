// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DetailList, Stack } from "./layout";

afterEach(cleanup);

describe("Stack", () => {
  it("renders a flex column with a token gap by default", () => {
    render(
      <Stack data-testid="stack">
        <span>a</span>
        <span>b</span>
      </Stack>,
    );
    const el = screen.getByTestId("stack");
    expect(el.tagName).toBe("DIV");
    expect(el.style.display).toBe("flex");
    expect(el.style.flexDirection).toBe("column");
    expect(el.style.gap).toBe("var(--space-2)");
  });

  it("renders the requested element with direction, gap, alignment and wrap", () => {
    render(
      <Stack data-testid="row" as="section" direction="row" gap={4} align="center" justify="space-between" wrap>
        <span>a</span>
      </Stack>,
    );
    const el = screen.getByTestId("row");
    expect(el.tagName).toBe("SECTION");
    expect(el.style.flexDirection).toBe("row");
    expect(el.style.gap).toBe("var(--space-4)");
    expect(el.style.alignItems).toBe("center");
    expect(el.style.justifyContent).toBe("space-between");
    expect(el.style.flexWrap).toBe("wrap");
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
