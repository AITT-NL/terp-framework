// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox } from "./ui/Checkbox";
import { Radio } from "./ui/Radio";
import { Switch } from "./ui/Switch";
import { Popover } from "./ui/Popover";
import { Tabs } from "./ui/Tabs";
import { TERP_STYLES_CSS } from "./styles";

// Defects the phases 1-4 review found, gated.
//
// Every one of these shipped past four browser lanes and a full unit suite, so an assertion that
// merely restates the fix would be worth nothing. Each row names the mutation that turns it red
// and was checked against it.
//
// Several read SOURCE TEXT or the stylesheet rather than behaviour, which is unusual here and
// deliberate rather than lazy. Each of those is a fact about something this suite cannot execute:
// what a DIFFERENT React major serializes, what an entry point no test mounts forwards, or which
// rule wins a cascade jsdom does not compute. A behavioural assertion would pass under the bug in
// every one of those cases. Where behaviour CAN see it — the frozen controls, the tabpanel's
// name, the popover's focus return — the test renders and asserts on the result instead.
//
// No count here on purpose: an earlier version of this comment said "two of the four" and was
// wrong by the time the file had ten. A citation keeps; a tally rots.
//
// One trap has now appeared twice in gates written for this very review, so it is worth stating
// where the next reader will meet it: a `toContain` on a CSS selector is satisfied by any LONGER
// selector containing it. `:root[data-density="x"]` contains `[data-density="x"]`, and the pager's
// own disabled rule contains the shared one. Both mutations came back GREEN until the assertions
// were anchored to the start of a line with a regex.

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

  it("gives a tabpanel an accessible name even when the tab value contains whitespace", () => {
    // `Tabs` built element ids by interpolating the caller's `value`. A value is caller data and
    // an id is an IDREF, so a value with a space turned `aria-labelledby` into a list of two
    // tokens, neither of which resolves — and the tabpanel silently lost its name. Nothing
    // reported it: axe sees a well-formed reference to nothing, and the visible tab still reads
    // correctly. Ids key on the tab's index now.
    // Mutation: interpolate `tab.value` / `selectedTab.value` back into the two ids.
    render(
      <Tabs
        label="Sections"
        tabs={[
          { value: "my tab", label: "My tab", content: <p>first</p> },
          { value: "other one", label: "Other one", content: <p>second</p> },
        ]}
      />,
    );
    expect(screen.getByRole("tabpanel", { name: "My tab" })).toBeInTheDocument();
  });

  it("wins the density tie against the contract's own :root declarations", () => {
    // The shell's density attribute sets the same custom properties the contract declares on
    // :root, both unlayered. A bare [data-density="..."] on <html> weighs (0,1,0) — exactly what
    // :root weighs — so the two tied and only the order the sheets happened to load decided it.
    // A production build extracts tokens.css to a <link> that precedes the injected sheet, so
    // react-core won by construction and the exposure was the dev server and any host loading
    // the tokens late. The :root-qualified copy is (0,2,0) and wins outright.
    // Mutation: drop either :root-qualified selector.
    for (const density of ["comfortable", "compact"] as const) {
      expect(TERP_STYLES_CSS).toContain(`:root[data-density="${density}"]`);
      // The unqualified copy stays, for a density island on a subtree where there is no :root.
      // Anchored to the start of a line, because `:root[data-density="x"]` CONTAINS
      // `[data-density="x"]` — a bare toContain here would be satisfied by the qualified copy
      // alone and could never notice the unqualified one being deleted.
      expect(TERP_STYLES_CSS).toMatch(
        new RegExp(`^\\[data-density="${density}"\\]`, "m"),
      );
    }
  });

  it("forwards logoDark from both sanctioned entry points", () => {
    // The third slot to exist on the shell and be unreachable from the entry points every app
    // uses, after `headerActions` — which ADR 0097's own Context complains about. This one was
    // worse: the project template instructs every new app to pass `logoDark` to `renderTerpApp`
    // (template/project/frontend/src/main.tsx.jinja), so the documented example did not
    // typecheck. Mutation: delete either forwarding line.
    //
    // Matched as "the option appears in what the prop is given" rather than as one exact
    // expression, because the exact expression changed the day `shell.brand` landed and the
    // invariant did not: the slot now prefers a declared PATH and falls back to the option, and
    // the old `toContain("logoDark={options.logoDark}")` failed on a router that still forwards
    // it perfectly. An assertion on a spelling fails for the wrong reason, which is only one
    // step better than passing for the wrong reason.
    const router = sources["./router.tsx"] ?? "";
    const bootstrap = sources["./bootstrap.tsx"] ?? "";
    expect(router, "router.tsx is not in the scanned sources").not.toBe("");
    expect(bootstrap, "bootstrap.tsx is not in the scanned sources").not.toBe("");
    expect(router).toMatch(/logoDark=\{[^}]*options\.logoDark/);
    // `logo=` alone would also match inside `logoDark=`; the negated class stops at the
    // first `}`, so this reads the whole expression the slot is given.
    expect(router).toMatch(/[^a-zA-Z]logo=\{[^}]*options\.logo}/);
    expect(bootstrap).toContain("logoDark: options.logoDark,");
    expect(bootstrap).toMatch(/logoDark\?: ReactNode;/);
  });

  it("returns focus to the trigger when Tab leaves a popover panel", () => {
    // The panel is portalled to the END of document.body, so with no Tab branch the
    // sequential-navigation starting point stayed inside a node at the wrong end of the
    // document: Tab out landed past every piece of page content, and Shift+Tab landed on the
    // last focusable element on the page rather than back on the control that opened it. `Menu`
    // has implemented the APG contract for this all along and documents the exact failure;
    // `Popover` carried the same portal with an Escape-only handler.
    // Mutation: delete the Tab branch from the panel's onKeyDown.
    render(
      <Popover trigger={<button type="button">Open</button>}>
        {() => (
          <button type="button">Inside</button>
        )}
      </Popover>,
    );
    const trigger = screen.getByRole("button", { name: "Open" });
    fireEvent.click(trigger);
    const inside = screen.getByRole("button", { name: "Inside" });
    inside.focus();
    expect(document.activeElement).toBe(inside);
    fireEvent.keyDown(inside, { key: "Tab" });
    // Closed, and focus is back on the trigger — from which the browser's own Tab default
    // moves on to whatever genuinely follows it in the document.
    expect(screen.queryByRole("button", { name: "Inside" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps a pager button focusable when its own click disables it", () => {
    // Each of the pager's four buttons has a bound condition recomputed from what its own click
    // just changed, so pressing "next" until the last page disabled the control the user was
    // operating — and a disabled element cannot hold focus, so the browser dropped it to
    // <body>. A keyboard user paging to the end lost their place at the moment they arrived.
    // Mutation: change aria-disabled back to disabled on the next/last pair.
    const pagination = sources["./dataview/DataViewPagination.tsx"] ?? "";
    expect(pagination, "DataViewPagination.tsx is not in the scanned sources").not.toBe("");
    expect(pagination, "the native disabled attribute drops focus to <body>").not.toContain(
      "disabled={atFirst}",
    );
    expect(pagination).not.toContain("disabled={atLast}");
    expect(pagination).toContain("aria-disabled={atLast || undefined}");
    expect(pagination).toContain("aria-disabled={atFirst || undefined}");
    // And the sheet must paint the announced state exactly as it painted the native one, or the
    // fix trades a focus bug for a visual one.
    // Both anchored to the start of a line. The pager rule CONTAINS the shared selector as a
    // substring, so a bare toContain on the shared one is satisfied by the pager rule alone
    // and cannot notice it being deleted — which is exactly what the mutation showed.
    expect(TERP_STYLES_CSS).toMatch(
      /^\[data-terp="iconbutton"\]\[aria-disabled="true"\]/m,
    );
    expect(TERP_STYLES_CSS).toMatch(
      /^\[data-terp="dataview-pager"\] > \[data-terp="iconbutton"\]\[aria-disabled="true"\]/m,
    );
  });

  it("caps Markdown's blocks in a measured shell, past its own boxless wrapper", () => {
    // Markdown is display: contents, so it generates no box — and a non-inherited property on a
    // boxless element is dropped. The measured-width rule is a child-star selector on the page's
    // body children, so it MATCHED the markdown wrapper and then had nothing to apply a width
    // to: prose ran the full width of a measured shell, on the one component whose entire
    // purpose is long-form text. The sheet's own comment beside the wrapper asserted that no
    // child-star selector existed in the sheet, which the measured-width rule had already
    // falsified. Mutation: delete the reach-through rule.
    expect(TERP_STYLES_CSS).toContain('[data-terp="page"] > [data-terp="markdown"] > *');
  });

  it("paints the account menu from the sidebar family it actually sits on", () => {
    // The trigger renders inside the sidebar (and inside the header group under
    // navPlacement="header", which takes the sidebar surface), so its ink against that
    // background is a pairing in play — but it read the NEUTRAL family, which the contrast gate
    // has no sidebar-scoped pairing for. Reading the sidebar family instead puts it under
    // `sidebar-text` and `sidebar-muted-text`, both already declared, so the gate covers it with
    // no new entries. Provably zero-diff: the two families are byte-equal in all five themes.
    //
    // The role marker renders TWICE — trigger and portalled panel — so it is scoped rather than
    // swapped; the panel is in document.body and the sidebar palette does not apply there.
    // Mutation: put --color-neutral-900 back on the trigger.
    const menuRule = TERP_STYLES_CSS.slice(
      TERP_STYLES_CSS.indexOf('[data-terp="user-menu"] [data-terp="menu-trigger"] {'),
    ).slice(0, 900);
    expect(menuRule).toContain("color: var(--color-sidebar-fg)");
    expect(menuRule).not.toContain("color: var(--color-neutral-900)");
    const roleRule = TERP_STYLES_CSS.slice(
      TERP_STYLES_CSS.indexOf('[data-terp="user-menu"] [data-terp="user-menu-role"] {'),
    ).slice(0, 120);
    expect(roleRule).toContain("color: var(--color-sidebar-muted)");
  });
});
