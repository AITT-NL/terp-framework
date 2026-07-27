// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { TERP_STYLES_ID, injectTerpStyles } from "./styles";

afterEach(() => {
  document.querySelectorAll(`style#${TERP_STYLES_ID}`).forEach((node) => node.remove());
});

describe("injectTerpStyles", () => {
  it("appends the stylesheet once and is idempotent on re-invocation", () => {
    injectTerpStyles();
    injectTerpStyles();
    injectTerpStyles();
    const nodes = document.querySelectorAll(`style#${TERP_STYLES_ID}`);
    expect(nodes.length).toBe(1);
    expect(nodes[0]?.textContent ?? "").toContain("data-terp");
    expect(nodes[0]?.textContent ?? "").toContain('[data-terp="input"][type="number"]');
    expect(nodes[0]?.textContent ?? "").toContain("::-webkit-inner-spin-button");
  });

  it("themes scrollbars against the token palette (thin, not the OS default)", () => {
    injectTerpStyles();
    const css = document.querySelector(`style#${TERP_STYLES_ID}`)?.textContent ?? "";
    expect(css).toContain("scrollbar-width: thin");
    expect(css).toContain("scrollbar-color: var(--color-neutral-300) transparent");
    expect(css).toContain("::-webkit-scrollbar");
    expect(css).toContain("::-webkit-scrollbar-thumb");
  });
});
