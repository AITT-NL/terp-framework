import type { NavItem } from "@terpjs/contract";
import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { Icon, NavIcon, TerpMark } from "./icons";
import { LanguageSwitcher } from "./locale";
import { injectTerpStyles } from "./styles";
import { ThemeToggle } from "./theme";
import { CONTROL_TEXT_STYLE } from "./ui/controlStyles";
import { useStrings, useUiText } from "./uiText";
import type { UiText } from "./uiText";

injectTerpStyles();

/** Context the shell passes to slot renderers (the collapsed icon-rail state). */
export interface AppShellSlotContext {
  collapsed: boolean;
}

export interface AppShellLinkContext extends AppShellSlotContext {
  style: CSSProperties;
  activeStyle: CSSProperties;
}

export type RenderBrandLink = (props: {
  to: string;
  children: ReactNode;
  style: CSSProperties;
}) => ReactNode;

export interface AppShellProps {
  /** Product / app title shown next to the logo at the top of the sidebar. */
  title: UiText;
  /** Sidebar nav, already filtered for the current user (see `visibleNav`). */
  nav: readonly NavItem[];
  /**
   * Turns a nav item into the active stack's link around the shell-styled
   * `children` (icon + label), keeping the shell router-agnostic. Spread
   * `context.style` (and `context.activeStyle` on the active route) onto the
   * link element — the shell owns the expanded/collapsed link geometry, so
   * every stack's links look identical in both rail states.
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
  /** The routed page content. */
  children: ReactNode;
}

/** The `localStorage` key the sidebar's collapsed choice persists under. */
export const SIDEBAR_STORAGE_KEY = "terp.sidebar";

/** Below this width the sidebar becomes an overlay drawer (matches DataView's card cutover). */
const MOBILE_BREAKPOINT = "(max-width: 768px)";

const EXPANDED_WIDTH = "15rem";
const COLLAPSED_WIDTH = "4rem";

/** Base style for sidebar links — spread onto the stack's link element. */
export const NAV_LINK_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  padding: "var(--space-2) var(--space-3)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-neutral-700)",
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
  textDecoration: "none",
  whiteSpace: "nowrap",
  overflow: "hidden",
  boxSizing: "border-box",
  minHeight: "2.25rem",
  transition: "background-color 150ms ease, color 150ms ease",
};

/** Collapsed rail geometry: one centered fixed-size icon inside the 2.5rem content track. */
export const NAV_LINK_COLLAPSED_STYLE: CSSProperties = {
  justifyContent: "center",
  gap: 0,
  padding: "var(--space-2)",
  width: "100%",
};

/** Merged over {@link NAV_LINK_STYLE} on the active route's link. */
export const NAV_LINK_ACTIVE_STYLE: CSSProperties = {
  background: "var(--color-brand-primary-soft)",
  color: "var(--color-brand-primary)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
};

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

function readStoredCollapsed(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

const shellStyle: CSSProperties = {
  display: "flex",
  alignItems: "stretch",
  minHeight: "100vh",
  fontFamily: "var(--font-family-sans)",
  color: "var(--color-neutral-900)",
  background: "var(--color-neutral-50)",
};

const sidebarStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-4)",
  padding: "var(--space-3)",
  boxSizing: "border-box",
  flexShrink: 0,
  position: "sticky",
  top: 0,
  height: "100vh",
  overflowX: "hidden",
  background: "var(--color-neutral-0)",
  borderRight: "1px solid var(--color-neutral-200)",
  transition: "width 150ms ease",
};

const drawerStyle: CSSProperties = {
  ...sidebarStyle,
  position: "fixed",
  inset: "0 auto 0 0",
  height: "100dvh",
  width: EXPANDED_WIDTH,
  zIndex: 50,
  boxShadow: "var(--shadow-lg)",
};

const backdropStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 40,
  background: "rgb(0 0 0 / 0.4)",
};

const brandStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  padding: "var(--space-1) var(--space-2)",
  minHeight: "2.25rem",
};

const brandLinkStyle: CSSProperties = {
  ...brandStyle,
  color: "var(--color-neutral-900)",
  textDecoration: "none",
  borderRadius: "var(--radius-md)",
  boxSizing: "border-box",
};

const drawerBrandRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
};

const brandTitleStyle: CSSProperties = {
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  fontSize: "var(--font-size-base)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
  color: "var(--color-neutral-900)",
  letterSpacing: 0,
};

const navItemLabelStyle: CSSProperties = {
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const visuallyHiddenStyle: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

const navStyle: CSSProperties = { flexGrow: 1, overflowY: "auto", minHeight: 0 };

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: "var(--space-1)",
};

const columnStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  flexGrow: 1,
  minWidth: 0,
};

const headerStyle: CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 30,
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  padding: "var(--space-2) var(--space-4)",
  minHeight: "3rem",
  boxSizing: "border-box",
  background: "var(--color-neutral-0)",
  borderBottom: "1px solid var(--color-neutral-200)",
};

const headerGroupStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
};

const mainStyle: CSSProperties = { flexGrow: 1, padding: "var(--space-6)", minWidth: 0 };
const mainMobileStyle: CSSProperties = { ...mainStyle, padding: "var(--space-4)" };

const footerStyle: CSSProperties = {
  padding: "var(--space-3) var(--space-6)",
  borderTop: "1px solid var(--color-neutral-200)",
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-xs)",
};

const toggleStyle: CSSProperties = {
  ...CONTROL_TEXT_STYLE,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "2.25rem",
  height: "2.25rem",
  padding: 0,
  color: "var(--color-neutral-700)",
  background: "transparent",
  border: "1px solid transparent",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
};

const defaultRenderBrandLink: RenderBrandLink = ({ to, children, style }) => (
  <a href={to} data-terp="appshell-brand" style={style}>
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
  children,
}: AppShellProps) {
  const resolve = useUiText();
  const strings = useStrings();
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(readStoredCollapsed);
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
  const linkStyle = railCollapsed
    ? { ...NAV_LINK_STYLE, ...NAV_LINK_COLLAPSED_STYLE }
    : NAV_LINK_STYLE;
  const resolvedTitle = resolve(title);

  const brand = renderBrandLink({
    to: "/",
    style: railCollapsed
      ? { ...brandLinkStyle, justifyContent: "center", paddingInline: 0 }
      : isMobile
        ? { ...brandLinkStyle, flex: 1, minWidth: 0 }
        : brandLinkStyle,
    children: (
      <>
        {logo ?? <TerpMark />}
        <strong style={railCollapsed ? visuallyHiddenStyle : brandTitleStyle}>
          {resolvedTitle}
        </strong>
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
      style={
        isMobile
          ? drawerStyle
          : { ...sidebarStyle, width: railCollapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH }
      }
    >
      {isMobile && (
        <span
          data-terp="drawer-focus-start"
          tabIndex={0}
          style={visuallyHiddenStyle}
          onFocus={() => focusDrawerEdge("last")}
        />
      )}
      {isMobile ? (
        <div
          style={drawerBrandRowStyle}
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
            style={toggleStyle}
            onClick={closeDrawer}
          >
            <Icon name="x" size="1.15rem" />
          </button>
        </div>
      ) : brand}
      <nav
        style={navStyle}
        data-terp="appshell-nav"
        data-collapsed={railCollapsed || undefined}
        aria-label={strings.primaryNavigationLabel}
        onClick={isMobile ? closeDrawer : undefined}
      >
        <ul style={listStyle}>
          {nav.map((item) => (
            <li key={item.to} title={railCollapsed ? item.label : undefined}>
              {renderLink(
                item,
                <>
                  <NavIcon name={item.icon} label={item.label} />
                  <span style={railCollapsed ? visuallyHiddenStyle : navItemLabelStyle}>
                    {item.label}
                  </span>
                </>,
                { collapsed: railCollapsed, style: linkStyle, activeStyle: NAV_LINK_ACTIVE_STYLE },
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
          style={visuallyHiddenStyle}
          onFocus={() => focusDrawerEdge("first")}
        />
      )}
    </aside>
  );

  return (
    <div style={shellStyle}>
      {isMobile ? (
        drawerOpen && (
          <>
            {/* Click-away surface only: Escape and the labelled header toggle are the
                accessible close paths, so the backdrop stays out of the a11y tree. */}
            <div aria-hidden="true" style={backdropStyle} onClick={closeDrawer} />
            {sidebar}
          </>
        )
      ) : (
        sidebar
      )}
      <div
        style={columnStyle}
        inert={isMobile && drawerOpen ? true : undefined}
        aria-hidden={isMobile && drawerOpen ? true : undefined}
      >
        <header style={headerStyle}>
          <button
            ref={toggleRef}
            type="button"
            data-terp="iconbutton"
            style={toggleStyle}
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
          <div style={headerGroupStyle}>
            {headerActions}
            <ThemeToggle variant="inline" />
            <LanguageSwitcher variant="inline" />
          </div>
        </header>
        <main style={isMobile ? mainMobileStyle : mainStyle}>{children}</main>
        <footer style={footerStyle}>{footer ?? <small>{resolvedTitle}</small>}</footer>
      </div>
    </div>
  );
}
