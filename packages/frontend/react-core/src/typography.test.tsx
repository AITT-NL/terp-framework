// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NavLinkContext } from "./navLink";
import { Code, Heading, Link, Text } from "./typography";

afterEach(cleanup);

describe("Heading", () => {
  it("takes its element from the level and its size from a separate default", () => {
    render(
      <>
        <Heading level={2}>two</Heading>
        <Heading level={3}>three</Heading>
        <Heading level={4}>four</Heading>
      </>,
    );
    for (const [level, size] of [
      [2, "lg"],
      [3, "base"],
      [4, "sm"],
    ] as const) {
      const el = screen.getByRole("heading", { level });
      expect(el.tagName).toBe(`H${level}`);
      expect(el).toHaveAttribute("data-size", size);
      expect(el.getAttribute("style")).toBeNull();
    }
  });

  it("lets a level carry any size, which is the point of separating them", () => {
    // A visually small h2 is a legitimate thing to want, and forcing level and size together
    // is what makes an author pick the wrong element to get the right size — breaking the
    // outline a screen-reader user navigates by, as a styling decision.
    render(
      <Heading level={2} size="sm">
        small but second
      </Heading>,
    );
    const el = screen.getByRole("heading", { level: 2 });
    expect(el.tagName).toBe("H2");
    expect(el).toHaveAttribute("data-size", "sm");
  });
});

describe("Text", () => {
  it("leaves the default tone and step unstamped", () => {
    render(<Text data-testid="copy">body</Text>);
    const el = screen.getByTestId("copy");
    expect(el.tagName).toBe("P");
    expect(el).toHaveAttribute("data-terp", "text");
    expect(el.hasAttribute("data-tone")).toBe(false);
    expect(el.hasAttribute("data-size")).toBe(false);
    expect(el.hasAttribute("data-measure")).toBe(false);
    expect(el.getAttribute("style")).toBeNull();
  });

  it("names a tone, a step, a measure and its element", () => {
    render(
      <Text data-testid="copy" as="span" tone="muted" size="sm" measure="narrow">
        body
      </Text>,
    );
    const el = screen.getByTestId("copy");
    expect(el.tagName).toBe("SPAN");
    expect(el).toHaveAttribute("data-tone", "muted");
    expect(el).toHaveAttribute("data-size", "sm");
    expect(el).toHaveAttribute("data-measure", "narrow");
  });
});

describe("Code", () => {
  it("is a bare code element when inline", () => {
    render(<Code data-testid="snippet">terp dev</Code>);
    const el = screen.getByTestId("snippet");
    expect(el.tagName).toBe("CODE");
    expect(el.hasAttribute("tabindex")).toBe(false);
  });

  it("wraps a block in a focusable pre, which is what preserves the whitespace", () => {
    // The `<pre>` is not decoration: a `<code>` alone collapses whitespace, so a multi-line
    // snippet in one runs together. And it scrolls, which is why it is focusable — a scroll
    // container a keyboard cannot reach cannot be scrolled at all (SC 2.1.1).
    render(<Code block>{"a\n  b"}</Code>);
    const pre = document.querySelector('[data-terp="code-block"]')!;
    expect(pre.tagName).toBe("PRE");
    expect(pre).toHaveAttribute("tabindex", "0");
    const code = pre.querySelector('[data-terp="code"]')!;
    expect(code.tagName).toBe("CODE");
    expect(code.textContent).toBe("a\n  b");
  });
});

describe("Link", () => {
  const renderer = ({ to, children }: { to: string; children: React.ReactNode }) => (
    <a href={`#routed${to}`} data-testid="routed">
      {children}
    </a>
  );

  it("routes an in-app path through the ambient renderer, marking a wrapper", () => {
    // `navLink` takes { to, children } and nothing else, so the router's own Link cannot be
    // handed an attribute — the marker lands on a wrapper and the rule reaches the anchor by
    // descending. HubCard's pattern, for the same unavoidable reason.
    render(
      <NavLinkContext.Provider value={renderer}>
        <Link to="/records">records</Link>
      </NavLinkContext.Provider>,
    );
    const anchor = screen.getByTestId("routed");
    expect(anchor.getAttribute("href")).toBe("#routed/records");
    const wrapper = anchor.parentElement!;
    expect(wrapper.tagName).toBe("SPAN");
    expect(wrapper).toHaveAttribute("data-terp", "link");
  });

  it("falls back to a plain anchor with no router above it", () => {
    // The story/test/bespoke-shell case, and the same degradation every layout component that
    // renders a link already does. Without it a Link outside a Terp router renders nothing
    // navigable at all.
    render(<Link to="/records">records</Link>);
    const el = screen.getByRole("link", { name: "records" });
    expect(el.tagName).toBe("A");
    expect(el).toHaveAttribute("href", "/records");
    expect(el).toHaveAttribute("data-terp", "link");
  });

  it("gives an external new tab rel=noreferrer, and adds neither otherwise", () => {
    // Without `rel`, the opened page can reach back through `window.opener` — the
    // reverse-tabnabbing shape the boundary lint's own no-unsafe-target-blank rule exists for.
    const { rerender } = render(
      <Link to="https://example.com" newTab>
        out
      </Link>,
    );
    const newTab = screen.getByRole("link", { name: "out" });
    expect(newTab).toHaveAttribute("target", "_blank");
    expect(newTab).toHaveAttribute("rel", "noreferrer");
    rerender(<Link to="https://example.com">out</Link>);
    const sameTab = screen.getByRole("link", { name: "out" });
    expect(sameTab.hasAttribute("target")).toBe(false);
    expect(sameTab.hasAttribute("rel")).toBe(false);
  });

  it("ignores newTab for an in-app path, which has no external tab to open", () => {
    render(
      <NavLinkContext.Provider value={renderer}>
        <Link to="/records" newTab>
          records
        </Link>
      </NavLinkContext.Provider>,
    );
    const anchor = screen.getByTestId("routed");
    expect(anchor.hasAttribute("target")).toBe(false);
  });
});
