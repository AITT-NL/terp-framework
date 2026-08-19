import type { NavItem } from "@terpjs/contract";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

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
  /** The routed page content. */
  children: ReactNode;
}

/** The `localStorage` key the sidebar's collapsed choice persists under. */
export const SIDEBAR_STORAGE_KEY = "terp.sidebar";

/** Below this width the sidebar becomes an overlay drawer (matches DataView's card cutover). */
const MOBILE_BREAKPOINT = "(max-width: 768px)";

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(MOBILE_BREAKPOINT).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(MOBILE_BREAKPOINT);
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
  navFooter,
  footer,
  defaultCollapsed = false,
  children,
}: AppShellProps) {
  const resolve = useUiText();
  const strings = useStrings();
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(() => readStoredCollapsed(defaultCollapsed));
  const [drawerOpen, setDrawerOpen] = useState(false);
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
    <div data-terp="appshell" data-variant={shellVariant}>
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
        <main data-terp="appshell-main">{children}</main>
        <footer data-terp="appshell-footer">{footer ?? <small>{resolvedTitle}</small>}</footer>
      </div>
    </div>
  );
}
