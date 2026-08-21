import type { NavItem } from "@terpjs/contract";
import { useCallback, useEffect, useRef, useState } from "react";
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

export interface AppShellProps {
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
  /** Pinned to the bottom of the sidebar (the {@link UserMenu}); may read the rail state. */
  navFooter?: ReactNode | ((context: AppShellSlotContext) => ReactNode);
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
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

/** The `localStorage` key the sidebar's collapsed choice persists under. */
export const SIDEBAR_STORAGE_KEY = "terp.sidebar";

/**
 * The id the skip link targets and `main` carries.
 *
 * Exported because an app rendering its own chrome around `buildAppRouter` still wants one
 * skip target rather than two, and a second literal is how the two would drift apart.
 */
export const MAIN_CONTENT_ID = "terp-main";

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
 *   mobile breakpoint it becomes an overlay drawer with a backdrop;
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

  // The drawer always shows labels; the desktop rail hides them when collapsed.
  const railCollapsed = !isMobile && collapsed;
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

  const sidebar = (
    <aside
      ref={isMobile ? drawerRef : undefined}
      role={isMobile ? "dialog" : undefined}
      aria-modal={isMobile ? true : undefined}
      // Named on BOTH branches now. The desktop aside is a complementary landmark and carried no
      // accessible name, so a screen reader's landmark list showed an anonymous region beside a
      // named one — the mobile branch had a label only because the dialog role demanded it.
      aria-label={strings.primaryNavigationLabel}
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
      {typeof navFooter === "function" ? navFooter(context) : navFooter}
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
    >
      {/* First in the DOM, so it is the first thing a keyboard reaches on load — which is the
          whole contract, and why it cannot be placed anywhere more convenient. Visually hidden
          until focused (the sheet shares that with the drawer's focus sentinels) and then
          painted above the sticky header.
          The shell owns this because the shell owns the landmarks: `main` is rendered here, and
          nothing above it knows the id to point at. */}
      <a data-terp="appshell-skip-link" href={`#${MAIN_CONTENT_ID}`}>
        {strings.skipToContent}
      </a>
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
        sidebar
      )}
      <div
        data-terp="appshell-column"
        inert={isMobile && drawerOpen ? true : undefined}
        aria-hidden={isMobile && drawerOpen ? true : undefined}
      >
        <header data-terp="appshell-header">
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
          <div data-terp="appshell-header-group">
            {headerActions}
            <ThemeToggle variant="inline" />
            <LanguageSwitcher variant="inline" />
          </div>
        </header>
        {/* tabIndex -1 so the skip link actually MOVES focus. Following a fragment link sets
            the sequential-navigation starting point, but a non-focusable target leaves
            document.activeElement on <body> — so the link would jump the viewport and leave the
            next Tab going back into the chrome it exists to skip. -1 keeps it out of the tab
            order while making it programmatically focusable, which is the whole trick. */}
        <main id={MAIN_CONTENT_ID} data-terp="appshell-main" tabIndex={-1}>
          {children}
        </main>
        <footer data-terp="appshell-footer">{footer ?? <small>{resolvedTitle}</small>}</footer>
      </div>
    </div>
  );
}
