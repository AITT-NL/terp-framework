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
  const renderer = ({
    to,
    children,
    attributes,
  }: {
    to: string;
    children: React.ReactNode;
    attributes?: Record<string, unknown>;
  }) => (
    <a href={`#routed${to}`} data-testid="routed" {...attributes}>
      {children}
    </a>
  );

  it("routes an in-app path through the ambient renderer, marking a wrapper", () => {
    // The marker lands on a wrapper the component owns, and that is deliberate rather than
    // forced: it could travel to the anchor through the renderer's `attributes`, and must not,
    // because an app supplying its own renderer that ignores them is source-compatible and the
    // failure would be an unstyled link with no error. A styling hook cannot depend on a caller
    // honouring a seam. HubCard's pattern, for a related reason.
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

  it("puts the caller's own attributes on the ANCHOR, in both branches", () => {
    // The defect this pins: `rest` used to land on the wrapper for an in-app path and on the
    // anchor for an external one, so the same prop worked or silently did nothing depending on
    // whether the destination started with a slash. An `aria-label` on a `<span>` around a link
    // is ignored — the link keeps its content as its name and the caller's intent disappears
    // with no error, which is the worst available failure.
    const { rerender } = render(
      <NavLinkContext.Provider value={renderer}>
        <Link to="/records" aria-label="All records" id="records-link">
          records
        </Link>
      </NavLinkContext.Provider>,
    );
    const routed = screen.getByRole("link", { name: "All records" });
    expect(routed.tagName).toBe("A");
    expect(routed.getAttribute("id")).toBe("records-link");

    rerender(
      <Link to="https://example.com" aria-label="The docs">
        docs
      </Link>,
    );
    expect(screen.getByRole("link", { name: "The docs" }).tagName).toBe("A");
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

  it("refuses a bare relative destination rather than reloading the page", () => {
    // The silent case this replaces: `to="records"` fell through to the external branch and
    // rendered a relative anchor — a full reload to a URL resolved against wherever the user
    // was, with the router's guard skipped. Every route a manifest declares is absolute, so
    // there is no reading of a bare path that is what the caller wanted.
    expect(() => render(<Link to="records">records</Link>)).toThrow(/leading slash/);
  });

  it("accepts a same-page fragment and a scheme, which are an anchor's own business", () => {
    render(
      <>
        <Link to="#section">jump</Link>
        <Link to="mailto:ops@example.com">mail</Link>
      </>,
    );
    expect(screen.getByRole("link", { name: "jump" })).toHaveAttribute("href", "#section");
    expect(screen.getByRole("link", { name: "mail" })).toHaveAttribute(
      "href",
      "mailto:ops@example.com",
    );
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
