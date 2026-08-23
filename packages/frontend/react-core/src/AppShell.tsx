import type { NavGroup, NavItem } from "@terpjs/contract";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import { NARROW_VIEWPORT } from "./breakpoints";
import { groupNav } from "./nav";
import { activeNavPath } from "./navActive";
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
export interface AppShellLinkContext extends AppShellSlotContext {
  /**
   * Whether this is the current item — the shell's verdict over the **whole set**, not this
   * link's opinion of itself.
   *
   * That distinction is the reason the field exists. "At most one item is current" cannot be
   * decided one link at a time, and a router decides exactly that way: give it `/settings` and
   * `/settings/users` and at `/settings/users` it marks both active, because each is a prefix
   * of the URL and neither knows the other exists. So the shell resolves the set once (longest
   * segment-aligned match wins, {@link activeNavPath}) and tells the renderer, which is free to
   * put the answer wherever its stack wants it — `aria-current` on a router link, in practice.
   *
   * `false` for every item when `activePath` is not given, so a shell that is not told where it
   * is claims nothing.
   */
  active: boolean;
}

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
  /**
   * Brand mark at the top of the sidebar; default: the {@link TerpMark} placeholder.
   *
   * It renders inside a box of `--shell-brand-size`, so an asset larger than the icon rail no
   * longer clips it — which is why there is no separate "collapsed mark" slot. The rail already
   * separates the two halves of a brand: `logo` is the mark and `title` is the wordmark, and
   * collapsing hides the title. An app whose logo is a wide lockup should split it that way
   * rather than supply a third asset.
   */
  logo?: ReactNode;
  /**
   * The mark to show on **dark-appearance** themes, when the app's brand does not survive one.
   *
   * The bundled icons all stroke in `currentColor` and need nothing here; a company mark
   * usually cannot, and a dark-ink one is invisible on three of the five shipped themes. Pass
   * this and both marks render, with CSS showing one — the theme is `<html data-theme>`, which
   * an app may set with no provider mounted at all, so resolving it in React would be wrong for
   * every shell that is not inside `renderTerpApp`.
   *
   * Which themes count as dark is not a list in the stylesheet. `themes.json` already declares
   * each theme's `appearance` and the token build emits the switch from it, so a sixth theme
   * cannot forget to answer.
   */
  logoDark?: ReactNode;
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
   * The current URL path, so the shell can decide which nav item is current.
   *
   * Absent stamps nothing and claims nothing — the `density` idiom — so a shell that is not told
   * where it is renders exactly what it renders today, and `renderLink` receives
   * `active: false` for every item. `buildAppRouter` passes the router's pathname; a bare shell
   * in a test or a specimen can pass a literal.
   *
   * A plain string rather than a router hook, because the shell is router-agnostic and must stay
   * so: it imports nothing from any stack. A query string or hash is tolerated and ignored —
   * a nav tab's identity is its path.
   */
  activePath?: string;
  /**
   * The app's declared navigation groups, which {@link nav} items reference by
   * `NavItem.group`.
   *
   * Absent renders exactly what the shell renders today: one unlabelled list holding every item
   * in the order it was given. That is `groupNav`'s identity case rather than a branch here — see
   * its docstring for the four rules, all of which are about a missing declaration.
   *
   * A group spans modules, so the **app** owns the label and the position and a module owns only
   * the reference. That is why this is a shell prop and `group` is a manifest field, rather than
   * both living on the manifest.
   */
  navGroups?: readonly NavGroup[];
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
  logoDark,
  headerActions,
  contentWidth = "full",
  density,
  activePath,
  navGroups,
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
  // The same per-instance guarantee, for the group labels. The workbench catalogue renders three
  // shells on one page, and a module-constant id would make the second shell's `aria-labelledby`
  // resolve into the first — a wrong accessible name rather than a missing one, which nothing
  // reports: `duplicate-id` is deprecated in axe and does not run, and a resolvable IDREF is not
  // a violation whatever it resolves to.
  const navGroupId = useId();
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
  // Resolved once over the whole set rather than per link — see AppShellLinkContext.active for
  // why that is the whole point. Undefined when nothing matches, and when nobody told the shell
  // where it is.
  const currentTo = activePath === undefined ? undefined : activeNavPath(activePath, nav);
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
  // A box of its own around the mark, which is the thing that makes an app's asset usable:
  // the rail is 4rem wide and the brand link used to hand whatever it was given straight to a
  // flex row, so an oversized logo was clipped by the aside's `overflow-x: hidden` with nothing
  // to say so. One declared size caps it in every placement.
  //
  // Both marks render when a dark one is given, and the SHEET picks — see `logoDark`. When it
  // is not, there is one child and no attribute, so the common case adds a wrapper and nothing
  // else.
  const mark = logo ?? <TerpMark />;
  const brand = renderBrandLink({
    to: "/",
    children: (
      <>
        <span data-terp="appshell-mark">
          {logoDark === undefined ? (
            mark
          ) : (
            <>
              <span data-appearance="light">{mark}</span>
              <span data-appearance="dark">{logoDark}</span>
            </>
          )}
        </span>
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
      {groupNav(nav, navGroups).map((section, index) => {
        // Only a labelled section needs an id, and only a DECLARED section can be labelled — the
        // default one has no declaration to carry a label. Keyed on the index rather than on
        // `section.id`: a group id is an app-supplied string, and whitespace in one would
        // silently break the IDREF rather than fail anywhere.
        const labelId = section.label === null ? undefined : `${navGroupId}-${index}`;
        return (
          // No heading element, and this is the decision rather than an oversight. `Heading`
          // refuses level 1 to reserve it for the routed view's title (see typography.tsx), and
          // the sidebar renders BEFORE `<main>` — so a heading per group would put chrome above
          // every page's h1 in the document outline, on every page in the product. axe cannot
          // see it either: `heading-order` is a best-practice rule, outside the tags the a11y
          // lane runs, and h2 -> h1 is a decrease that the rule passes anyway. A labelled list
          // says the same thing to a screen reader and says nothing to the outline.
          //
          // The wrapper is rendered even for the single default section, which costs one <div>
          // and no pixels: every rule in the sheet that reaches this subtree is an attribute or
          // descendant selector, so none of them cares that the <ul> gained a parent. One code
          // path is worth more than a branch that exists to save an element.
          //
          // A nav with NO visible items renders no wrapper and no list at all, where it used to
          // render an empty <ul>. That is the same "a section with no items is not emitted" rule
          // reaching its degenerate case rather than a second decision, it moves nothing (an
          // empty grid list has no height), and it takes an empty `list` role back out of the
          // accessibility tree. Reachable whenever every item is gated away by role or grant.
          <div key={index} data-terp="appshell-nav-group">
            {labelId !== undefined && (
              <span id={labelId} data-terp="appshell-nav-group-label">
                {section.label}
              </span>
            )}
            <ul data-terp="appshell-nav-list" aria-labelledby={labelId}>
              {section.items.map((item) => (
                <li key={item.to} title={railCollapsed ? item.label : undefined}>
                  {renderLink(
                    item,
                    <>
                      <NavIcon name={item.icon} label={item.label} />
                      <span data-terp="appshell-nav-label">{item.label}</span>
                    </>,
                    { collapsed: railCollapsed, active: item.to === currentTo },
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
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
        // `inert` is why this package requires React 19, and the requirement is real rather
        // than nominal. Measured against both renderers with renderToStaticMarkup:
        //
        //   spelling        React 18.3.1              React 19.2.8
        //   inert={true}    DROPPED (warns)           inert=""
        //   inert=""        inert=""                  DROPPED (warns: treated as false)
        //   inert="true"    inert=""                  inert="" (warns)
        //
        // So on 18.3 this pair degraded to the worst possible half — a subtree announced as
        // hidden to assistive technology while every control in it stayed focusable and
        // clickable, because `aria-hidden` is an aria-* attribute React has always passed
        // through. There is no spelling that is both correct and quiet on the two majors, which
        // is why the fix is the peer range (now ^19) rather than a cast here: the defect was
        // claiming to support a version on which the containment silently did not exist.
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
