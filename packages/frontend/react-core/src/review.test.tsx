// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox } from "./ui/Checkbox";
import { Radio } from "./ui/Radio";
import { Switch } from "./ui/Switch";
import { TERP_STYLES_CSS } from "./styles";

// Defects the phases 1-4 review found, gated.
//
// Every one of these shipped past four browser lanes and a full unit suite, so an assertion that
// merely restates the fix would be worth nothing. Each row names the mutation that turns it red
// and was checked against it.
//
// Two of the four read SOURCE TEXT rather than behaviour, which is unusual here and deliberate.
// `inert` and the `logoDark` pass-through are both facts about what gets serialized or forwarded
// under a React major and an entry point this suite does not run — React 19 renders either
// spelling of `inert` identically, and no test mounts `renderTerpApp`'s full option surface — so
// a behavioural assertion would pass under the bug. The source form is the only thing that
// distinguishes them here; the honest alternative is a CI matrix on React 18.3, which is a
// harness change rather than a test.

const sources = import.meta.glob("./**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The package manifest as text, so the peer range can be asserted without importing it. */
const packageJson = import.meta.glob("../package.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

afterEach(() => {
  cleanup();
});

describe("defects the phases 1-4 review found", () => {
  it("warns when a checked control is given no onChange, instead of freezing silently", () => {
    // React's own guard is the only thing that would tell an author they pinned `checked` and
    // forgot the handler. Passing `onChange` unconditionally suppresses it, so the control looked
    // operable, never changed, and said nothing — the exact failure `Select` documents at its own
    // call site (ui/Select.tsx) and avoids. Mutation: restore the unconditional handler in any of
    // the three and the count drops.
    const seen: string[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      seen.push(args.map(String).join(" "));
    });
    try {
      render(
        <>
          <Checkbox label="frozen box" checked />
          <Switch label="frozen switch" checked />
          <Radio name="group" value="a" label="frozen radio" checked />
        </>,
      );
    } finally {
      spy.mockRestore();
    }
    // React de-duplicates this warning per component type, so three distinct components warn
    // three times. Matched loosely because the exact wording differs across React majors.
    const complaints = seen.filter((line) => /without an .?onChange.? handler/.test(line));
    expect(complaints).toHaveLength(3);
  });

  it("does not repaint an invalid field's border on hover", () => {
    // Both rules live in terp.state, so the cascade is decided by specificity alone: the hover
    // selector weighed (0,4,0) against the danger border's (0,2,0) and won. Pointing at a field
    // that had just failed validation removed its error border for as long as the pointer rested
    // there — and the pointer rests there precisely because the user is about to fix it.
    // Mutation: drop the :not([aria-invalid="true"]).
    expect(TERP_STYLES_CSS).toContain(
      '[data-terp="input"]:hover:not(:disabled):not(:focus):not([aria-invalid="true"])',
    );
    // And the unnarrowed aggressor must not exist anywhere, in any form.
    expect(TERP_STYLES_CSS).not.toContain(
      '[data-terp="input"]:hover:not(:disabled):not(:focus) {',
    );
  });

  it("does not promise a React major on which the drawer's containment does not exist", () => {
    // The drawer inerts the page column and marks it aria-hidden. Measured with
    // renderToStaticMarkup against both renderers:
    //
    //   spelling        React 18.3.1              React 19.2.8
    //   inert={true}    DROPPED (warns)           inert=""
    //   inert=""        inert=""                  DROPPED (warns: treated as false)
    //
    // So under the old `^18.3.0 || ^19.0.0` peer range, an app on 18.3 got the worst half of
    // the pair — a subtree announced as hidden to assistive technology with every control in it
    // still focusable and clickable — and no spelling is correct and quiet on both. The review
    // that found this proposed `inert=""`, which would have broken React 19 instead; the
    // measurement is the only reason that did not ship. The defect is the promise, so the fix
    // is the range. Mutation: widen the peer range back to include ^18.3.0.
    const manifest = JSON.parse(
      (packageJson as Record<string, string>)["../package.json"] ?? "{}",
    ) as { peerDependencies?: Record<string, string> };
    const peers = manifest.peerDependencies ?? {};
    for (const name of ["react", "react-dom"] as const) {
      expect(peers[name], `${name} peer range`).toBeDefined();
      expect(peers[name]).not.toMatch(/18\./);
    }
    // And the attribute stays the spelling React 19 actually renders.
    const shell = sources["./AppShell.tsx"] ?? "";
    expect(shell, "AppShell.tsx is not in the scanned sources").not.toBe("");
    expect(shell).toContain("inert={isMobile && drawerOpen ? true : undefined}");
  });

  it("forwards logoDark from both sanctioned entry points", () => {
    // The third slot to exist on the shell and be unreachable from the entry points every app
    // uses, after `headerActions` — which ADR 0097's own Context complains about. This one was
    // worse: the project template instructs every new app to pass `logoDark` to `renderTerpApp`
    // (template/project/frontend/src/main.tsx.jinja), so the documented example did not
    // typecheck. Mutation: delete either forwarding line.
    const router = sources["./router.tsx"] ?? "";
    const bootstrap = sources["./bootstrap.tsx"] ?? "";
    expect(router, "router.tsx is not in the scanned sources").not.toBe("");
    expect(bootstrap, "bootstrap.tsx is not in the scanned sources").not.toBe("");
    expect(router).toContain("logoDark={options.logoDark}");
    expect(bootstrap).toContain("logoDark: options.logoDark,");
    expect(bootstrap).toMatch(/logoDark\?: ReactNode;/);
  });
});
