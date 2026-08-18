// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

afterEach(cleanup);

describe("Markdown", () => {
  it("renders common markdown blocks and inline formatting", () => {
    render(
      <Markdown
        source={`# Title\n\nA **bold** and *em* paragraph with \`code\`.\n\n- One\n- Two\n\n1. First\n2. Second\n\n\`\`\`\nconst ok = true;\n\`\`\``}
      />,
    );
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("em").tagName).toBe("EM");
    expect(screen.getByText("const ok = true;")).toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
  });

  it("allows only safe links and renders raw html as text", () => {
    const { container } = render(
      <Markdown source={'[safe](records/1) [bad](javascript:alert(1)) <img src=x onerror=alert(1)>'} />,
    );
    expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute("href", "records/1");
    expect(screen.queryByRole("link", { name: "bad" })).not.toBeInTheDocument();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
  it("wraps its blocks in a boxless root, and renders nothing at all when empty", () => {
    const { container } = render(
      <Markdown
        source={`# Title

Body paragraph.`}
      />,
    );
    const root = container.querySelector('[data-terp="markdown"]');
    expect(root).not.toBeNull();
    // The wrapper exists so the component can be found and styled at all. It is boxless by
    // rule — display: contents lives in the sheet — which is what keeps these blocks
    // individual items of any parent that spaces its children with gap, so marking the
    // component changed no consumer's layout.
    expect(root!.children.length).toBe(2);
    expect(root!.getAttribute("style")).toBeNull();

    cleanup();
    // An empty source still renders NOTHING, and that is load-bearing rather than tidy: the
    // layout contract's runtime check reads the direct children of a governed body slot and
    // refuses any marker its allow table does not name. An unconditional wrapper would turn
    // an empty Markdown beside allowed components from a passing body into a fail-closed
    // refusal — thrown for rendering no content.
    const empty = render(<Markdown source="   " />);
    expect(empty.container.firstChild).toBeNull();
  });
});
