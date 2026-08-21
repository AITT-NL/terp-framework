import type { NavItem } from "@terpjs/contract";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import { NARROW_VIEWPORT } from "./breakpoints";
import { Icon, NavIcon, TerpMark } from "./icons";
import { LanguageSwitcher } from "./locale";
import { injectTerpStyles } from "./styles";
import { ThemeToggle } from "./theme";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

/** Context the shell passes to slot renderers (the collapsed icon-rail state). */
export interface AppShellSlotContext {
  collapsed: boolean;
}

/**
 * What a link renderer is told about the shell it is rendering into.
 *
 * It used to carry `style` and `activeStyle` for the caller to spread, which made the
 * shell's link geometry a style object handed across a public boundary — unthemeable by
 * an app, and duplicated by every stack. The sheet owns that geometry now, keyed on
 * `[data-terp="appshell-nav"] a` and on `aria-current="page"` for the active route, so a
 * renderer needs to return nothing but its stack's link (ADR 0094).
 */
export type AppShellLinkContext = AppShellSlotContext;

export type RenderBrandLink = (props: { to: string; children: ReactNode }) => ReactNode;

interface AppShellBaseProps {
  /** Product / app title shown next to the logo at the top of the sidebar. */
  title: UiText;
  /** Sidebar nav, already filtered for the current user (see `visibleNav`). */
  nav: readonly NavItem[];
  /**
   * Turns a nav item into the active stack's link around the shell-styled
   * `children` (icon + label), keeping the shell router-agnostic. Return the
   * stack's link and nothing else: the shell owns the expanded and collapsed
   * link geometry from its stylesheet, and the active route's treatment is
   * keyed on `aria-current="page"`, which every router sets.
   */
  renderLink: (item: NavItem, children: ReactNode, context: AppShellLinkContext) => ReactNode;
  /** Turns the product brand into the home link; defaults to a plain anchor to `/`. */
  renderBrandLink?: RenderBrandLink;
  /** Brand mark at the top of the sidebar; default: the {@link TerpMark} placeholder. */
  logo?: ReactNode;
  /** Extra header content, rendered before the theme / language controls. */
  headerActions?: ReactNode;
  /**
   * Cap the routed content at the published measure (`--shell-content-max-width`), leaving
   * each page's own header spanning the full track above it.
   *
   * `"full"` is the default and stamps **nothing**, which is the density prop's shape and for
   * the same reason: full width is what the sheet already does, so an attribute for it would
   * match no rule. So no existing app moves by a pixel until it asks.
   *
   * The measure and the full-width band are one mechanism rather than two features — a band
   * only reads as a band once the column beside it is narrower — and the mechanism is the page
   * grid it already had, not a portal and not a wrapper. Both alternatives were rejected on
   * facts about this codebase rather than taste; see ADR 0097 §2 and the rule in `styles.ts`.
   *
   * "Full width" means the full width of the article's own track. `appshell-main`'s padding
   * sits outside it, so this is a measure within the content column rather than a bleed to the
   * window edge — which would need a negative margin, and therefore an inline site.
   */
  contentWidth?: "full" | "measured";
  /**
   * App-wide density, stamped on the shell root. **No default**, and that matters.
   *
   * The tokens do the work through inheritance, so every control and every cell in the tree
   * follows without a prop of its own, and a subtree can override it — a
   * `DataView density="comfortable"` inside a compact shell really is comfortable now, which
   * it was not before this prop existed. That island is the vocabulary ADR 0094 deferred until
   * something asked; this is what asked.
   *
   * Omitting the prop stamps **nothing**, rather than stamping `"comfortable"`. A default that
   * stamped would silently override `data-density` on `<html>` — which ADR 0094 §4 names as
   * *the app-wide case* and which an app sets from its own `theme.css` today. An unasked-for
   * shell prop must not win against an app-wide choice, so absence means "inherit whatever is
   * above me" and the two values mean what they say.
   */
  density?: "comfortable" | "compact";
  /** Pinned to the bottom of the sidebar (the {@link UserMenu}); may read the rail state. */
  navFooter?: ReactNode | ((context: AppShellSlotContext) => ReactNode);
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
  /**
   * Start with the mobile drawer open.
   *
   * The same door `defaultCollapsed` opened for the icon rail, for the same reason and with the
   * same evidence behind it. Below the breakpoint the sidebar renders **only** while
   * `drawerOpen` is true, and that is internal state with no way in — so the drawer's own
   * geometry (`position: fixed`, `100dvh`, the drawer z-index, the shadow) and its backdrop
   * have shipped unpainted, asserted in `styles.test.ts` as text with "no baseline can hold it"
   * written beside them. Four rules, true for four releases.
   *
   * Dev/specimen affordance rather than an app-facing one: an app opening the drawer on load
   * is showing every mobile user a menu they did not ask for. It exists so the rules can be
   * photographed.
   */
  defaultDrawerOpen?: boolean;
  /** The routed page content. */
  children: ReactNode;
}

/**
 * Where the primary navigation lives, and it is a union rather than two independent props
 * because one combination of them would be legal and inert.
 *
 * `"sidebar"` is the default and stamps nothing — full-height chrome on the left, collapsing
 * to an icon rail, which is every shell the framework has rendered so far. `"header"` moves
 * the nav into the header as a horizontal row and drops the sidebar entirely, for an app whose
 * destinations are few enough that 15rem of permanent chrome is a tax: the template's `portal`
 * preset names that app in as many words — "a personal landing for customers, staff or
 * suppliers" — and today it renders into chrome designed for a 21-module internal tool.
 *
 * **Desktop only.** Below the breakpoint both placements are the drawer, because a horizontal
 * row of links does not fit a 420px viewport and the drawer already exists. So this changes
 * nothing a phone renders, which is also why the attribute is derived from the viewport rather
 * than stamped from the prop.
 *
 * `defaultCollapsed` is `never` under `"header"`: with no sidebar there is nothing to collapse,
 * so the pair would type-check, do nothing, and give no sign of it — the shape this phase keeps
 * refusing, most recently in `Select`'s options union.
 */
type AppShellNavPlacementProps =
  | {
      navPlacement?: "sidebar";
      /**
       * Start with the desktop sidebar collapsed to its icon rail, when no choice has been
       * persisted yet. The user's own toggle still wins and still persists.
       *
       * It exists for the same reason `Menu` and both date pickers take `defaultOpen`: the
       * rail is internal state read from `localStorage`, so without a way in it can be
       * rendered by no specimen and no test, and every rule that only applies to it is
       * unpainted. Four were.
       */
      defaultCollapsed?: boolean;
    }
  | { navPlacement: "header"; defaultCollapsed?: never };

export type AppShellProps = AppShellBaseProps & AppShellNavPlacementProps;

/** The `localStorage` key the sidebar's collapsed choice persists under. */
export const SIDEBAR_STORAGE_KEY = "terp.sidebar";

/*
 * The skip link's target id is per-INSTANCE (see `useId` below), not a module constant.
 *
 * A constant was the first shape and it is wrong wherever two shells mount together: every one
 * of them renders `<main id="terp-main">` and a link to `#terp-main`, so the ids collide and
 * each link jumps to the first shell on the page rather than to its own content. The workbench
 * catalogue is exactly that page — three shells at once — which is how it was found. It was
 * also documented as exported and never actually re-exported from the entry point, so the one
 * argument for a shared constant had no consumer either.
 */

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(NARROW_VIEWPORT).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(NARROW_VIEWPORT);
    const onChange = (event: MediaQueryListEvent) => setIsMobile(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}

/**
 * The persisted rail choice, falling back to `defaultCollapsed` when nothing is stored.
 *
 * The null check is the whole point and it is new: reading `=== "collapsed"` treated an
 * absent key and an explicit "expanded" as the same thing, so a `defaultCollapsed` shell
 * could never start collapsed. A stored choice still wins in both directions.
 */
function readStoredCollapsed(fallback: boolean): boolean {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const stored = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    return stored === null ? fallback : stored === "collapsed";
  } catch {
    return fallback;
  }
}

const defaultRenderBrandLink: RenderBrandLink = ({ to, children }) => (
  <a href={to} data-terp="appshell-brand">
    {children}
  </a>
);

function PanelIcon() {
  return (
    <svg
      width="1.25em"
      height="1.25em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      aria-hidden="true"
      focusable={false}
    >
      <rect x="3" y="4.5" width="18" height="15" rx="1.5" />
      <path d="M9.5 4.5v15" />
    </svg>
  );
}

/**
 * The app shell every Terp screen lives in — responsive and mobile-ready by default:
 *
 * - a full-height sidebar: brand (logo + title) on top, the role-filtered nav with
 *   per-item icons, and the `navFooter` (the {@link UserMenu}) pinned to the bottom.
 *   On desktop it collapses to an icon rail (persisted in `localStorage`); below the
 *   mobile breakpoint it becomes an overlay drawer with a backdrop. With
 *   `navPlacement="header"` there is no sidebar on desktop at all: the same brand, the same
 *   nav and the same user menu render in the header, and the drawer still handles mobile;
 * - a **sticky** header over the content: the sidebar toggle on the left, then
 *   `headerActions` and the standard theme + language controls on the right;
 * - the routed `children` in a `main` landmark, with a slim `footer` underneath.
 *
 * Router-agnostic: `renderLink` wraps the shell-styled icon + label in the active
 * stack's link. Landmarks (`header` / `nav` / `main` / `footer`) keep it accessible.
 */
export function AppShell({
  title,
  nav,
  renderLink,
  renderBrandLink = defaultRenderBrandLink,
  logo,
  headerActions,
  contentWidth = "full",
  density,
  navPlacement = "sidebar",
  navFooter,
  footer,
  defaultCollapsed = false,
  defaultDrawerOpen = false,
  children,
}: AppShellProps) {
  const resolve = useUiText();
  const strings = useStrings();
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(() => readStoredCollapsed(defaultCollapsed));
  const [drawerOpen, setDrawerOpen] = useState(defaultDrawerOpen);
  // Per shell instance, so two shells on one page get two distinct skip targets.
  const mainId = useId();
  const drawerRef = useRef<HTMLElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  useEffect(() => {
    if (!isMobile || !drawerOpen) {
      return;
    }
    drawerCloseRef.current?.focus();
    return () => {
      window.setTimeout(() => toggleRef.current?.focus(), 0);
    };
  }, [isMobile, drawerOpen]);

  function onDrawerKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
    }
  }

  function focusDrawerEdge(edge: "first" | "last") {
    const focusable = drawerRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled)',
    );
    const target = edge === "first" ? focusable?.[0] : focusable?.[focusable.length - 1];
    (target ?? drawerRef.current)?.focus();
  }

  useEffect(() => {
    if (!isMobile || !drawerOpen) {
      return;
    }
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [isMobile, drawerOpen]);

  function toggleSidebar() {
    if (isMobile) {
      setDrawerOpen((current) => !current);
      return;
    }
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "collapsed" : "expanded");
      } catch {
        // Private mode / quota: the choice still applies for this session.
      }
      return next;
    });
  }

  // Desktop only, and derived rather than stamped from the prop: below the breakpoint both
  // placements ARE the drawer, so a shell asked for a header nav on a phone renders exactly
  // what it renders today. Deriving it here is what lets every rule keyed on the attribute skip
  // a [data-variant="desktop"] guard — the attribute is absent whenever it would not be true.
  const headerNav = !isMobile && navPlacement === "header";
  // The drawer always shows labels; the desktop rail hides them when collapsed. `headerNav`
  // forces it false rather than leaving the persisted choice to leak: with no sidebar the
  // attribute lands nowhere, but `context.collapsed` still reaches `renderLink` and
  // `navFooter`, so a user who had collapsed the rail before the app moved its nav would get
  // icon-only links in a header with room for labels.
  const railCollapsed = !isMobile && !headerNav && collapsed;
  const context: AppShellSlotContext = { collapsed: railCollapsed };
  // Hoisted, the density-attribute idiom: the marker scanner reads a whole expression
  // container, so a conditional written at the attribute reports every literal in it as a
  // marker name.
  const collapsedAttribute = railCollapsed ? "true" : undefined;
  // One attribute for the viewport, on the shell root, and every consequence of it descends
  // from there: the sidebar becomes a drawer, main tightens its padding. The breakpoint stays
  // in one place — this component's media query — rather than being restated as a CSS
  // @media rule that could drift from it.
  const shellVariant = isMobile ? "mobile" : "desktop";
  // Hoisted for the same reason `collapsedAttribute` is: the default stamps nothing, so the
  // expression has a branch, and a conditional written at the attribute is the form the marker
  // scanner reads every literal out of.
  const contentWidthAttribute = contentWidth === "measured" ? "measured" : undefined;
  // Stamped for whichever value was ASKED for, and for neither when the prop is absent.
  // Both values now have a rule — comfortable is no longer the absence of an attribute — so
  // passing it is a real instruction rather than a no-op. Passing nothing has to stay a
  // no-op, or the shell would override an app's own <html data-density>.
  const densityAttribute = density;
  const navPlacementAttribute = headerNav ? "header" : undefined;
  const resolvedTitle = resolve(title);

  // The brand takes no style object and needs none: its three looks are the resting one,
  // the collapsed one (reached from the sidebar's data-collapsed) and the mobile one
  // (reached from the drawer's brand row, which only exists on mobile). The DOM already
  // says which it is.
  const brand = renderBrandLink({
    to: "/",
    children: (
      <>
        {logo ?? <TerpMark />}
        <strong data-terp="appshell-brand-title">{resolvedTitle}</strong>
      </>
    ),
  });

  // Hoisted out of the aside, because the header placement renders the SAME nodes in a
  // different parent — same markers, same link renderer, same labels. Which is the point:
  // the two placements are one navigation with two geometries, not two navigations, so
  // nothing about a link's identity or its active state depends on where it sits.
  const navigation = (
    <nav
      data-terp="appshell-nav"
      aria-label={strings.primaryNavigationLabel}
      onClick={isMobile ? closeDrawer : undefined}
    >
      <ul data-terp="appshell-nav-list">
        {nav.map((item) => (
          <li key={item.to} title={railCollapsed ? item.label : undefined}>
            {renderLink(
              item,
              <>
                <NavIcon name={item.icon} label={item.label} />
                <span data-terp="appshell-nav-label">{item.label}</span>
              </>,
              { collapsed: railCollapsed },
            )}
          </li>
        ))}
      </ul>
    </nav>
  );

  // The user menu. Pinned to the bottom of the sidebar when there is one, and last in the
  // header group when there is not — losing it entirely is the failure a placement prop
  // invites, since it is where an app puts sign-out.
  const footerSlot = typeof navFooter === "function" ? navFooter(context) : navFooter;

  const sidebar = (
    <aside
      ref={isMobile ? drawerRef : undefined}
      role={isMobile ? "dialog" : undefined}
      aria-modal={isMobile ? true : undefined}
      // Mobile only, which is where it started. Labelling the desktop aside as well looked like
      // an improvement and was not: the `nav` immediately inside it already carries this exact
      // string, so the landmark list gained a "Primary" complementary containing a "Primary"
      // navigation — two nested entries with the same name, which is the disambiguation failure
      // `SplitPane` documents rather than a fix for it. An unnamed complementary wrapping a
      // named navigation is the lesser problem; giving the aside a name of its own is a
      // separate decision with a string to choose, not a side effect of adding a skip link.
      aria-label={isMobile ? strings.primaryNavigationLabel : undefined}
      tabIndex={isMobile ? -1 : undefined}
      onKeyDown={isMobile ? onDrawerKeyDown : undefined}
      data-terp="appshell-sidebar"
      data-collapsed={collapsedAttribute}
    >
      {isMobile && (
        <span
          data-terp="drawer-focus-start"
          tabIndex={0}
          onFocus={() => focusDrawerEdge("last")}
        />
      )}
      {isMobile ? (
        <div
          data-terp="appshell-brand-row"
          onClick={(event) => {
            if (event.target instanceof Element && event.target.closest("a") !== null) {
              closeDrawer();
            }
          }}
        >
          {brand}
          <button
            ref={drawerCloseRef}
            type="button"
            data-terp="iconbutton"
            aria-label={strings.closeNavigation}
            onClick={closeDrawer}
          >
            <Icon name="x" size="1.15rem" />
          </button>
        </div>
      ) : brand}
      {navigation}
      {footerSlot}
      {isMobile && (
        <span
          data-terp="drawer-focus-end"
          tabIndex={0}
          onFocus={() => focusDrawerEdge("first")}
        />
      )}
    </aside>
  );

  return (
    <div
      data-terp="appshell"
      data-variant={shellVariant}
      data-content-width={contentWidthAttribute}
      data-density={densityAttribute}
      data-nav-placement={navPlacementAttribute}
    >
      {/* First in the DOM, so it is the first thing a keyboard reaches on load — which is the
          whole contract, and why it cannot be placed anywhere more convenient. Visually hidden
          until focused (the sheet shares that with the drawer's focus sentinels) and then
          painted above the sticky header.
          The shell owns this because the shell owns the landmarks: `main` is rendered here, and
          nothing above it knows the id to point at.

          NOT rendered while the mobile drawer is open, and that is a correctness fix rather
          than tidying. The drawer is role="dialog" aria-modal, and the column below carries
          `inert` — so this link is the one element that contradicts both: it sits outside the
          modal, outside the inert subtree, and points AT the inert subtree. Whether a keyboard
          route to it exists depends on where the browser's sequential-navigation starting point
          happens to be, which is not a thing an accessibility guarantee should rest on. With
          the drawer open there is also nothing to skip to. */}
      {!(isMobile && drawerOpen) && (
        <a data-terp="appshell-skip-link" href={`#${mainId}`}>
          {strings.skipToContent}
        </a>
      )}
      {isMobile ? (
        drawerOpen && (
          <>
            {/* Click-away surface only: Escape and the labelled header toggle are the
                accessible close paths, so the backdrop stays out of the a11y tree. */}
            <div aria-hidden="true" data-terp="appshell-backdrop" onClick={closeDrawer} />
            {sidebar}
          </>
        )
      ) : (
        !headerNav && sidebar
      )}
      <div
        data-terp="appshell-column"
        inert={isMobile && drawerOpen ? true : undefined}
        aria-hidden={isMobile && drawerOpen ? true : undefined}
      >
        <header data-terp="appshell-header">
          {/* No toggle under the header placement, and that is a correctness point rather
              than tidying: the control exists to collapse the sidebar, and there is no
              sidebar. Rendering it anyway would leave an aria-expanded whose target does not
              exist — a button announcing a state about nothing. The brand takes the slot
              instead, which is the other thing the sidebar was carrying. */}
          {headerNav ? (
            brand
          ) : (
            <button
              ref={toggleRef}
              type="button"
              data-terp="iconbutton"
              aria-expanded={isMobile ? drawerOpen : !collapsed}
              aria-label={
                isMobile
                  ? drawerOpen
                    ? strings.closeNavigation
                    : strings.openNavigation
                  : collapsed
                    ? strings.expandSidebar
                    : strings.collapseSidebar
              }
              onClick={toggleSidebar}
            >
              <PanelIcon />
            </button>
          )}
          {headerNav && navigation}
          <div data-terp="appshell-header-group">
            {headerActions}
            <ThemeToggle variant="inline" />
            <LanguageSwitcher variant="inline" />
            {headerNav && footerSlot}
          </div>
        </header>
        {/* tabIndex -1 so the skip link actually MOVES focus. Following a fragment link sets
            the sequential-navigation starting point, but a non-focusable target leaves
            document.activeElement on <body> — so the link would jump the viewport and leave the
            next Tab going back into the chrome it exists to skip. -1 keeps it out of the tab
            order while making it programmatically focusable, which is the whole trick. */}
        <main id={mainId} data-terp="appshell-main" tabIndex={-1}>
          {children}
        </main>
        <footer data-terp="appshell-footer">{footer ?? <small>{resolvedTitle}</small>}</footer>
      </div>
    </div>
  );
}
