// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NavItem } from "@terpjs/contract";

import { AppShell, SIDEBAR_STORAGE_KEY } from "./AppShell";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const nav: NavItem[] = [
  { label: "Notes", to: "/notes", icon: "list" },
  { label: "Users", to: "/users", role: "admin" },
];

function renderShell(extra?: Partial<Parameters<typeof AppShell>[0]>) {
  return render(
    <AppShell
      title="Terp"
      nav={nav}
      renderLink={(item, children) => <a href={item.to}>{children}</a>}
      navFooter={<p>pinned footer</p>}
      {...extra}
    >
      <p>page content</p>
    </AppShell>,
  );
}

/** Make the shell believe it is below the mobile breakpoint. */
function stubMobileViewport() {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
}

describe("AppShell", () => {
  it("renders the landmarks, brand, and the nav via renderLink — and NO footer", () => {
    renderShell();

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    // No `contentinfo` unless the app asks for one. The default used to be a strip
    // restating the app title already in the header and the browser tab — on every screen
    // of every app, costing vertical space on exactly the viewports with least of it. An
    // empty landmark is worse than none: it is somewhere a screen-reader user can navigate
    // to and find nothing.
    expect(screen.queryByRole("contentinfo")).toBeNull();
    // The brand is the standard home affordance.
    expect(screen.getAllByText("Terp").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("link", { name: "Terp" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Notes" })).toHaveAttribute("href", "/notes");
    expect(screen.getByText("page content")).toBeInTheDocument();
    // The navFooter slot renders inside the sidebar (pinned chrome, e.g. UserMenu).
    expect(screen.getByText("pinned footer")).toBeInTheDocument();
  });

  it("collapses to an icon rail and persists the choice", () => {
    renderShell({ navFooter: ({ collapsed }) => <p>{collapsed ? "rail" : "full"}</p> });

    expect(screen.getByText("full")).toBeInTheDocument();
    expect(screen.getByText("Notes")).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
    fireEvent.click(toggle);

    // Labels remain as accessible names; fixed icon slots and the fallback tile remain visible.
    expect(screen.getByRole("link", { name: "Notes" })).toBeInTheDocument();
    expect(screen.getByText("U")).toBeInTheDocument(); // Users' fallback initial tile
    const navigation = screen.getByRole("navigation", { name: "Primary" });
    // data-collapsed is on the SIDEBAR, not on the nav. One fact, one owner: the rail decides
    // the sidebar's width, the brand's centring, the nav's scrollbar and both hidden labels, so
    // every rule that reads it descends from the element that owns it.
    const sidebar = navigation.closest('[data-terp="appshell-sidebar"]');
    expect(sidebar).toHaveAttribute("data-collapsed", "true");
    expect(navigation.querySelectorAll('[data-terp="nav-icon"]')).toHaveLength(2);
    // The link's collapsed geometry is a rule now, keyed on that attribute — asserting
    // toHaveStyle here asserted that the shell hands a style object to the caller's link
    // renderer, which is the thing this migration removed. jsdom computes no cascade, so the
    // fact is what a unit test can hold; the geometry is gated by styles.test.ts and by the
    // app-shell-collapsed baseline.
    expect(screen.getByRole("link", { name: "Notes" })).not.toHaveAttribute("style");
    expect(screen.getByText("rail")).toBeInTheDocument();
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("restores the collapsed rail from localStorage", () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    renderShell();
    expect(screen.getByRole("link", { name: "Notes" })).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Primary" }).closest('[data-terp="appshell-sidebar"]'),
    ).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("starts collapsed on defaultCollapsed, and a stored choice still wins", () => {
    // The rail was internal state with no way in, which is why four rules that apply only to it
    // were painted by nothing. Reading the key with `=== "collapsed"` also treated an absent key
    // and an explicit "expanded" as the same thing, so the fallback had to become a null check.
    renderShell({ defaultCollapsed: true });
    expect(
      screen.getByRole("navigation", { name: "Primary" }).closest('[data-terp="appshell-sidebar"]'),
    ).toHaveAttribute("data-collapsed", "true");
    cleanup();

    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "expanded");
    renderShell({ defaultCollapsed: true });
    expect(
      screen.getByRole("navigation", { name: "Primary" }).closest('[data-terp="appshell-sidebar"]'),
      "an explicit stored choice must beat defaultCollapsed, in both directions",
    ).not.toHaveAttribute("data-collapsed");
  });

  it("stamps no density unless one is asked for, so an app's own html-level choice wins", () => {
    // The regression this exists to prevent shipped for one commit. The prop was defaulted to
    // "comfortable" and stamped unconditionally, which reads as harmless — comfortable is the
    // :root value, after all. It is not: comfortable now has a RULE of its own (that is what
    // makes an island possible), so stamping it on the shell root overrides
    // `data-density="compact"` set on <html>, which ADR 0094 section 4 names as the app-wide
    // case and which an app sets from its own theme.css.
    //
    // So absence has to mean "inherit whatever is above me". The two values mean what they say.
    const { unmount } = renderShell();
    expect(
      document.querySelector('[data-terp="appshell"]'),
      "an unasked-for shell prop must not beat an app-wide choice",
    ).not.toHaveAttribute("data-density");
    unmount();

    renderShell({ density: "compact" });
    expect(document.querySelector('[data-terp="appshell"]')).toHaveAttribute(
      "data-density",
      "compact",
    );
    cleanup();

    // And comfortable IS stamped when asked for, because it is now an instruction rather than
    // a no-op: it is how a shell inside something compact says it is not.
    renderShell({ density: "comfortable" });
    expect(document.querySelector('[data-terp="appshell"]')).toHaveAttribute(
      "data-density",
      "comfortable",
    );
  });

  it("stamps data-content-width only when the measure is asked for", () => {
    // The default has to stamp NOTHING, and that is the assertion rather than a detail: the
    // rule is keyed on `[data-content-width="measured"]`, so an attribute for the full-width
    // case would match nothing while looking like it configured something — and every app on
    // the default must render byte-identically to before the prop existed.
    const { unmount } = renderShell();
    expect(document.querySelector('[data-terp="appshell"]')).not.toHaveAttribute(
      "data-content-width",
    );
    unmount();

    renderShell({ contentWidth: "full" });
    expect(
      document.querySelector('[data-terp="appshell"]'),
      'contentWidth="full" is the sheet\'s own behaviour, so it stamps no attribute',
    ).not.toHaveAttribute("data-content-width");
    cleanup();

    renderShell({ contentWidth: "measured" });
    expect(document.querySelector('[data-terp="appshell"]')).toHaveAttribute(
      "data-content-width",
      "measured",
    );
  });

  it("keeps the measure attribute on the shell root, above the page it constrains", () => {
    // Ownership, which the selector depends on: the rule descends from the shell root to
    // `[data-terp="page"]`, so the attribute cannot live on `main` or on the page itself. A
    // later refactor moving it one element down would break the measure with no test failing
    // unless this says where it belongs.
    renderShell({ contentWidth: "measured" });
    const root = document.querySelector('[data-terp="appshell"]')!;
    expect(root.getAttribute("data-content-width")).toBe("measured");
    for (const marker of ["appshell-column", "appshell-main", "appshell-header"]) {
      expect(
        document.querySelector(`[data-terp="${marker}"]`),
        `${marker} must not carry the measure attribute — the rule keys on the shell root`,
      ).not.toHaveAttribute("data-content-width");
    }
  });

  it("renders a custom logo and footer in their slots", () => {
    renderShell({ logo: <span>MyMark</span>, footer: <span>v1.2.3</span> });
    expect(screen.getByText("MyMark")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("v1.2.3");
  });

  it("becomes a modal drawer on mobile: contains focus, inerts the page, and closes on nav", async () => {
    stubMobileViewport();
    renderShell();

    // Closed drawer: no nav in the tree, only the header toggle.
    const toggle = screen.getByRole("button", { name: "Open navigation" });
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();

    fireEvent.click(toggle);
    const dialog = screen.getByRole("dialog", { name: "Primary" });
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    const close = screen.getByRole("button", { name: "Close navigation" });
    await waitFor(() => expect(close).toHaveFocus());
    expect(document.body.style.overflow).toBe("hidden");
    const background = screen.getByText("page content").closest("main")?.parentElement;
    expect(background).toHaveAttribute("inert");
    expect(background).toHaveAttribute("aria-hidden", "true");

    // The end focus sentinel wraps natural forward tabbing to the first drawer link.
    const endGuard = dialog.querySelector('[data-terp="drawer-focus-end"]')!;
    fireEvent.focus(endGuard);
    await waitFor(() => expect(screen.getByRole("link", { name: "Terp" })).toHaveFocus());
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    // Choosing a destination closes the drawer.
    fireEvent.click(screen.getByRole("link", { name: "Notes" }));
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    await waitFor(() => expect(toggle).toHaveFocus());
  });

  it("closes the mobile drawer when the product brand navigates home", () => {
    stubMobileViewport();
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    fireEvent.click(screen.getByRole("link", { name: "Terp" }));
    expect(screen.queryByRole("dialog", { name: "Primary" })).not.toBeInTheDocument();
  });

  it("closes the mobile drawer on Escape", () => {
    stubMobileViewport();
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Primary" }), { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
  });

  describe("the brand mark", () => {
    it("gives the mark a box of its own, with one child when there is no dark pair", () => {
      renderShell({ logo: <img src="/logo.svg" alt="" /> });

      const box = document.querySelector('[data-terp="appshell-mark"]');
      expect(box).not.toBeNull();
      expect(box!.children).toHaveLength(1);
      // No attribute in the common case: the switch exists only when there is something to
      // switch between, so an app that passes one asset renders one node and no mechanism.
      expect(box!.querySelector("[data-appearance]")).toBeNull();
    });

    it("renders both marks when a dark one is given, and labels which is which", () => {
      renderShell({
        logo: <img src="/logo-light.svg" alt="" />,
        logoDark: <img src="/logo-dark.svg" alt="" />,
      });

      const box = document.querySelector('[data-terp="appshell-mark"]')!;
      // Both are in the DOM and the SHEET picks — the theme is `<html data-theme>`, which an
      // app may set with no provider mounted, so a React branch would be wrong for every shell
      // outside `renderTerpApp`. That is why this asserts presence rather than absence.
      expect(box.querySelector('[data-appearance="light"] img')).toHaveAttribute(
        "src",
        "/logo-light.svg",
      );
      expect(box.querySelector('[data-appearance="dark"] img')).toHaveAttribute(
        "src",
        "/logo-dark.svg",
      );
    });
  });

  describe('navPlacement="header"', () => {
    it("moves the whole navigation into the header and renders no sidebar", () => {
      renderShell({ navPlacement: "header" });

      const header = screen.getByRole("banner");
      const navigation = screen.getByRole("navigation", { name: "Primary" });
      // The same nav, in a different parent — the assertion is containment rather than
      // existence, because existence passes in both placements.
      expect(header).toContainElement(navigation);
      expect(header).toContainElement(screen.getByRole("link", { name: "Terp" }));
      // The user menu follows it. Losing it is the failure a placement prop invites, since it
      // is where an app puts sign-out and the sidebar was the only thing holding it.
      expect(header).toContainElement(screen.getByText("pinned footer"));
      expect(document.querySelector('[data-terp="appshell-sidebar"]')).toBeNull();
      expect(document.querySelector('[data-terp="appshell"]')).toHaveAttribute(
        "data-nav-placement",
        "header",
      );
    });

    it("renders no sidebar toggle, because there is no sidebar to collapse", () => {
      renderShell({ navPlacement: "header" });

      // Not a tidying assertion: the button carries aria-expanded, so rendering it would
      // announce a state about an element that does not exist.
      expect(screen.queryByRole("button", { name: "Collapse sidebar" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Expand sidebar" })).toBeNull();
      expect(document.querySelector("[aria-expanded]")).toBeNull();
    });

    it("does not leak a persisted rail choice into the header's link context", () => {
      // The regression this exists for: `collapsed` is persisted, so a user who had collapsed
      // the rail before the app moved its nav would get icon-only links in a header with room
      // for labels — and the sidebar attribute that normally reveals the state lands nowhere.
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
      renderShell({
        navPlacement: "header",
        navFooter: ({ collapsed }) => <p>{collapsed ? "rail" : "full"}</p>,
      });

      expect(screen.getByText("full")).toBeInTheDocument();
    });

    it("is desktop-only: below the breakpoint it is still the drawer", () => {
      stubMobileViewport();
      renderShell({ navPlacement: "header" });

      // The attribute is derived from the viewport, not stamped from the prop, which is what
      // lets every rule keyed on it skip a [data-variant] guard.
      expect(document.querySelector('[data-terp="appshell"]')).not.toHaveAttribute(
        "data-nav-placement",
      );
      expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      expect(screen.getByRole("dialog", { name: "Primary" })).toBeInTheDocument();
    });
  });
});

// Navigation groups, as the shell renders them.
//
// Every assertion here is on the SHELL'S OUTPUT, never on a fixture literal. That distinction is
// the one this phase keeps paying for: nine AppShell specimens hand-write `aria-current` in their
// own renderLink, so no baseline gates the shell's active paint at all. A group label read back
// from the string that was passed in would be the same mistake.
//
// The name queries are `getByRole("list", { name })` rather than `toHaveAttribute`, and that is a
// gate decision rather than a style one. A dropped or dangling `aria-labelledby` is not a
// violation any lane in this repo can see — axe files a bad IDREF as `incomplete`, and the a11y
// lane reads `results.violations` only — so the accessible NAME has to be the thing asserted, and
// only a name query computes it.
describe("AppShell navigation groups", () => {
  const grouped: NavItem[] = [
    { label: "Notes", to: "/notes", group: "work" },
    { label: "Reports", to: "/reports", group: "work" },
    { label: "Loose", to: "/loose" },
  ];

  it("labels each group's list with its own visible label", () => {
    render(
      <AppShell
        title="Terp"
        nav={grouped}
        navGroups={[{ id: "work", label: "Werkruimte" }]}
        renderLink={(item, children) => <a href={item.to}>{children}</a>}
      >
        <p>page content</p>
      </AppShell>,
    );

    // The accessible name is computed from the rendered span, so this is red on a dropped
    // attribute AND on an id that resolves nowhere.
    const labelled = screen.getByRole("list", { name: "Werkruimte" });
    expect(labelled).toBeInTheDocument();
    expect(
      [...labelled.querySelectorAll("a")].map((anchor) => anchor.getAttribute("href")),
    ).toEqual(["/notes", "/reports"]);
    // The ungrouped bucket is a second list, and it has no name of its own.
    expect(screen.getAllByRole("list")).toHaveLength(2);
  });

  it("gives two shells on one page distinct label ids", () => {
    // The workbench catalogue renders three shells on one page. With a module-constant id the
    // second shell's `aria-labelledby` resolves into the FIRST shell's span — a wrong accessible
    // name rather than a missing one, which nothing reports: `duplicate-id` is deprecated in axe
    // and does not run, and a resolvable IDREF is not a violation whatever it points at.
    // Mutation: replace `useId()` with a module constant, and the two ids below become equal.
    const shell = (label: string) => (
      <AppShell
        title="Terp"
        nav={[{ label: "Notes", to: "/notes", group: "g" }]}
        navGroups={[{ id: "g", label }]}
        renderLink={(item, children) => <a href={item.to}>{children}</a>}
      >
        <p>page content</p>
      </AppShell>
    );
    render(
      <>
        {shell("Eerste")}
        {shell("Tweede")}
      </>,
    );

    const ids = screen
      .getAllByRole("list")
      .map((list) => list.getAttribute("aria-labelledby"));
    expect(ids.filter(Boolean)).toHaveLength(2);
    expect(new Set(ids)).toHaveProperty("size", 2);
    // And each one still resolves to its OWN label, which is what the distinct ids are for.
    expect(screen.getByRole("list", { name: "Eerste" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Tweede" })).toBeInTheDocument();
  });

  it("renders no label element and no aria-labelledby for the default group", () => {
    // The additive case: a shell given no groups at all must render exactly what it renders
    // today, plus the wrapper. Mutation: render a span for a null label.
    const { container } = renderShell();

    expect(container.querySelectorAll('[data-terp="appshell-nav-group"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-terp="appshell-nav-group-label"]')).toHaveLength(0);
    expect(
      container.querySelector('[data-terp="appshell-nav-list"]')?.hasAttribute("aria-labelledby"),
    ).toBe(false);
  });

  it("renders nothing at all for a group no visible item references", () => {
    // Reachable on a first render: `visibleNav` removes the role-gated `/admin` entry for
    // everyone else, so a group holding only it arrives here empty.
    // Mutation: emit the empty section, and the label appears over no links.
    const { container } = render(
      <AppShell
        title="Terp"
        nav={[{ label: "Loose", to: "/loose" }]}
        navGroups={[{ id: "beheer", label: "Beheer" }]}
        renderLink={(item, children) => <a href={item.to}>{children}</a>}
      >
        <p>page content</p>
      </AppShell>,
    );

    expect(screen.queryByText("Beheer")).not.toBeInTheDocument();
    expect(container.querySelectorAll('[data-terp="appshell-nav-group"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-terp="appshell-nav-group-label"]')).toHaveLength(0);
  });

  it("renders no wrapper and no list when every item is gated away", () => {
    // The degenerate case of "a section with no items is not emitted", and a real change: the
    // shell used to render an empty <ul> here. It moves nothing — an empty grid list has no
    // height — and it takes an empty `list` role back out of the accessibility tree, which is
    // why it is pinned rather than worked around. Reachable whenever `visibleNav` removes every
    // item, e.g. a viewer in an app whose whole nav is role-gated.
    // Mutation: emit the ungrouped section unconditionally, and an empty list reappears.
    const { container } = render(
      <AppShell title="Terp" nav={[]} renderLink={(item, children) => <a href={item.to}>{children}</a>}>
        <p>page content</p>
      </AppShell>,
    );

    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-terp="appshell-nav-group"]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-terp="appshell-nav-list"]')).toHaveLength(0);
    expect(screen.queryAllByRole("list")).toHaveLength(0);
  });

  it("renders no heading element anywhere in the navigation", () => {
    // The decision the prose argues and nothing enforced. `Heading` refuses level 1 to reserve
    // the outline for the routed view's title, and the sidebar renders BEFORE `<main>` — so a
    // heading per group would sit above every page's h1 on every page in the product. axe cannot
    // catch it: `heading-order` is best-practice, outside the lane's tags, and h2 -> h1 is a
    // decrease that passes anyway. Mutation: render the label as an <h2>.
    render(
      <AppShell
        title="Terp"
        nav={grouped}
        navGroups={[{ id: "work", label: "Werkruimte" }]}
        renderLink={(item, children) => <a href={item.to}>{children}</a>}
      >
        <p>page content</p>
      </AppShell>,
    );

    const navigation = screen.getByRole("navigation", { name: "Primary" });
    expect(navigation.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
    // The label is still there and still announced — this is not "no label", it is "no heading".
    expect(screen.getByText("Werkruimte")).toBeInTheDocument();
  });
});
