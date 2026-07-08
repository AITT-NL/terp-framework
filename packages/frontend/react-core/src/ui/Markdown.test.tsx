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
});
