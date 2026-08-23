import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  useNavigate,
  useParams,
  useRouter,
  useRouterState,
  useSearch,
  type AnyRoute,
  type RouterHistory,
} from "@tanstack/react-router";
import type { ComponentType, ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ModuleManifest, NavGroup } from "@terpjs/contract";

import { AppShell } from "./AppShell";
import { ProfileView } from "./ProfileView";
import type {
  TerpNavigateTarget,
  TerpRouteParamName,
  TerpRouteParams,
  TerpRoutePath,
  TerpRouteSearch,
} from "./routeTypes";
import { LAYOUT_CONTRACTS, LayoutContractContext } from "./layoutContract";
import { isDeclarationVisible, visibleNav } from "./nav";
import { NavLinkContext } from "./navLink";
import type { NavLinkRenderer } from "./navLink";
import { PageMarkerContext } from "./pageMarker";
import {
  RouteSearchContext,
  declaredSearchKeys,
  indexSearchKeys,
  useRouteSearchIndex,
} from "./routeSearch";
import { useAuth } from "./TerpProvider";
import { UserMenu } from "./UserMenu";
import { useStrings } from "./uiText";

/** Default role-name -> minimum rank map (the bundled viewer/editor/admin ladder). */
export const DEFAULT_ROLE_RANKS: Record<string, number> = {
  viewer: 10,
  editor: 20,
  admin: 30,
};

/** The built-in profile / settings route (an app manifest claiming the path wins). */
export const PROFILE_PATH = "/profile";

/**
 * Translate a manifest path into TanStack Router's dialect.
 *
 * `ModuleManifest` is stack-agnostic (the same manifest is meant to drive a SvelteKit
 * adapter, where a param is `[id]`), so it spells a parameter the neutral way: `:id`.
 * TanStack wants `$id`. Passing the manifest path through untranslated produced the
 * worst possible failure — a route that simply never matches, caught by nothing: not
 * the boundary lint, not typecheck, not the build, just a 404 at runtime for anyone who
 * followed the documented example. Both spellings are accepted (`$id` is what shipped
 * before this translation existed and what existing apps wrote); `:id` is canonical.
 */
export function routerPath(path: string): string {
  return path.replace(/(^|\/):([A-Za-z_][A-Za-z0-9_]*)/g, "$1$$$2");
}

/** Read the router's params bag, whatever route matched (a hook: it reads router state). */
function useCurrentParams(): Record<string, string | undefined> {
  return useParams({ strict: false }) as Record<string, string | undefined>;
}

/** The shared refusal both param reads raise, phrased as a directive. */
function missingParam(name: string, params: Record<string, string | undefined>): Error {
  const seen = Object.keys(params);
  return new Error(
    `Route param "${name}" is not present on the current route (params seen: ` +
      `${seen.length > 0 ? seen.join(", ") : "none"}). A param is declared in the ` +
      `module manifest's route path (e.g. "/records/:${name}") and must be read ` +
      "under that route — check the name against the manifest, and run `terp routes` " +
      "if the manifest changed.",
  );
}

/**
 * Read one route param by name, fail closed — the untyped core.
 *
 * Internal on purpose. The app-facing {@link useRouteParam} checks the name against the
 * app's generated route table, and this package's own packaged screens (the admin area)
 * must NOT be checked against it: their routes come from this package's manifest, not
 * from the app's, so constraining them to the app's declared params would fail an app
 * that simply declares no params of its own. A packaged screen's route correctness is
 * this package's own test surface.
 */
export function useDeclaredParam(name: string): string {
  const params = useCurrentParams();
  const value = params[name];
  if (value === undefined) {
    throw missingParam(name, params);
  }
  return value;
}

/**
 * Read one route param, fail closed when it is absent.
 *
 * The name is checked against the app's generated route table when there is one
 * ({@link TerpRouteParamName} — every param name any manifest route declares), and is
 * a plain `string` before `terp routes` has generated. Either way a name the *current*
 * route did not declare throws a directive error instead of silently yielding
 * `undefined`, which is what the raw `useParams({ strict: false }) as {…}` cast did.
 *
 * Reach for {@link useRouteParams} when you want the exact, per-route check: keyed by
 * the route path, it refuses a param that route does not declare, not merely one no
 * route declares.
 */
export function useRouteParam(name: TerpRouteParamName): string {
  return useDeclaredParam(name);
}

/**
 * Read a declared route's params as a typed object — the exact read (ADR 0092).
 *
 * ```tsx
 * const { recordId } = useRouteParams("/records/:recordId");
 * ```
 *
 * Once `terp routes` has generated the app's route table, the path must be one the
 * manifests declare and the returned object carries exactly that route's params, so a
 * typo in either the path or a param name is a typecheck error rather than a runtime
 * surprise. Before generating, the path is a plain `string` and the result is a
 * string-keyed record.
 *
 * The path is the manifest's stack-agnostic spelling (`:recordId`). Every declared
 * param must be present at runtime; a missing one fails closed, which is how a stale
 * generated table (manifest changed, `terp routes` not re-run) surfaces as an error
 * naming the param instead of `undefined` flowing into a request.
 */
export function useRouteParams<P extends TerpRoutePath>(path: P): TerpRouteParams<P> {
  const params = useCurrentParams();
  const declared = declaredParamNames(path);
  const resolved: Record<string, string> = {};
  for (const name of declared) {
    const value = params[name];
    if (value === undefined) {
      throw missingParam(name, params);
    }
    resolved[name] = value;
  }
  return resolved as TerpRouteParams<P>;
}

/** The param names a manifest path declares, in declaration order (`:name` segments). */
function declaredParamNames(path: string): string[] {
  return [...path.matchAll(/(?:^|\/)[:$]([A-Za-z_][A-Za-z0-9_]*)/g)].map((match) => match[1]!);
}

/**
 * Navigate to a declared route, with that route's params (ADR 0092).
 *
 * ```tsx
 * const navigate = useTerpNavigate();
 * void navigate({ to: "/records/:recordId", params: { recordId: row.id } });
 * ```
 *
 * The reason to prefer this over the router's own `navigate`: once the route table is
 * generated, an undeclared path is a typecheck error, a parameterised route *requires*
 * its params, and the param names are the manifest's. A typo'd path was previously a
 * dead link that shipped green — nothing checked it, because the route tree is built at
 * runtime. Paths are written in the manifest spelling and translated to the router's
 * dialect here ({@link routerPath}), so callers never hold two spellings.
 */
export function useTerpNavigate(): (target: TerpNavigateTarget) => Promise<void> {
  const navigate = useNavigate();
  return (target: TerpNavigateTarget) =>
    navigate({
      to: routerPath(target.to),
      // The reducer form, not a bare object: on a router whose route tree is built at
      // runtime TanStack types `params` as a reducer (or `true`), and merging over the
      // previous params is also the honest semantic for an in-place param change.
      params: (previous: Record<string, unknown>) => ({ ...previous, ...(target.params ?? {}) }),
      // Search is REPLACED, not merged (ADR 0096). Merging reads as convenient and is the
      // wrong default for the case this exists to serve: clearing a filter means sending
      // the key as undefined, and a merge would keep the old value instead — so "clear"
      // would silently not clear. A screen that wants to keep other keys passes them,
      // which is also the only form that stays checkable against the declared key set.
      search: dropUndefined(target.search),
    });
}

/**
 * Drop `undefined` values so a cleared filter leaves the URL instead of appearing as
 * `?status=undefined`, and an all-cleared search yields a bare path.
 */
function dropUndefined(
  search: Record<string, string | undefined> | undefined,
): Record<string, string> {
  const kept: Record<string, string> = {};
  for (const [key, value] of Object.entries(search ?? {})) {
    if (value !== undefined) {
      kept[key] = value;
    }
  }
  return kept;
}

/**
 * Read the current route's declared query-string keys (ADR 0096).
 *
 * ```tsx
 * const { status, page } = useRouteSearch("/records");
 * ```
 *
 * Every key is `string | undefined`, because a query parameter is text and is absent
 * until someone sets it — so a screen destructures with defaults rather than branching on
 * a bag of `unknown`. Reading a key the route did not declare is a typecheck error once
 * `terp routes` has generated; before that the shape is loose, exactly like the params
 * helpers. Undeclared keys present in the URL are **not** returned: the declaration is the
 * surface, so a stray key someone hand-typed cannot leak into a screen's logic.
 */
export function useRouteSearch<P extends TerpRoutePath>(path: P): TerpRouteSearch<P> {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const declared = declaredSearchKeys(useRouteSearchIndex(), path);
  const resolved: Record<string, string | undefined> = {};
  for (const name of declared) {
    const value = search[name];
    resolved[name] = typeof value === "string" ? value : undefined;
  }
  return resolved as TerpRouteSearch<P>;
}

export interface BuildAppRouterOptions {
  /** Maps a manifest route's `view` id to the component that renders it. */
  views: Record<string, ComponentType>;
  /** App title shown in the shell's sidebar brand. */
  title: string;
  /** Brand mark in the sidebar (any rendered node); default: the placeholder TerpMark. */
  logo?: ReactNode;
  /**
   * The dark-theme brand mark ({@link AppShell.logoDark}); the stylesheet picks per appearance.
   *
   * Forwarded because it was not, which made it the third slot to exist on the shell and be
   * unreachable from the entry points every app uses — after `headerActions`, which this ADR's
   * own Context complains about. This one was worse than unreachable: the project template
   * instructs every new app to pass `logoDark` to `renderTerpApp`, so the documented example
   * did not typecheck.
   */
  logoDark?: ReactNode;
  /** Extra header content, rendered before the theme / language controls. */
  headerActions?: ReactNode;
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
  /**
   * Cap routed content at the published measure, with each page's header on the full track
   * ({@link AppShell.contentWidth}); default `"full"`, which changes nothing.
   */
  contentWidth?: "full" | "measured";
  /**
   * App-wide density ({@link AppShell.density}). **No default** — omitting it stamps nothing, so
   * an app's own `data-density` on `<html>` still reaches the tree.
   */
  density?: "comfortable" | "compact";
  /**
   * Where the primary navigation lives on desktop ({@link AppShell.navPlacement}): the
   * full-height `"sidebar"` (default, and what every shell renders today) or `"header"`, a
   * horizontal row in the header with no sidebar at all. Below the mobile breakpoint both are
   * the drawer.
   */
  navPlacement?: "sidebar" | "header";
  /**
   * The app's navigation groups ({@link AppShell.navGroups}), which manifest items reference by
   * `NavItem.group`. Omit for the flat, unlabelled sidebar every app renders today.
   *
   * A duplicate id is refused here rather than tolerated: it is an authoring error with no
   * legitimate transient form, and composition time is where it can be reported once instead of
   * on every render. An item naming an *undeclared* group is the opposite case and is not an
   * error at all — modules ship independently of the app, so `groupNav` lets it fall open.
   */
  navGroups?: readonly NavGroup[];
  /** Role-name -> minimum rank; an unknown role is denied (fail closed). */
  roleRanks?: Record<string, number>;
  /** Rendered when the current user may not access a route (default: a simple message). */
  unauthorized?: ComponentType;
  /**
   * Opt into a slot-typed layout contract (ADR 0079), e.g. `"standard"`: every routed
   * archetype's body slot then accepts only the components the contract allows there,
   * verified at runtime (fail closed) with the same directive message the
   * `terp/layout-contract` lint rule phrases. Keep it in sync with the app's checked-in
   * `layout-contract.json` (the lint half). Omit for today's archetype-only behavior.
   */
  layoutContract?: string;
  /** Router history (e.g. `createMemoryHistory`); omit for the browser history. */
  history?: RouterHistory;
}

/** Whether a user with `roleRank` (null = signed out) may access a route requiring `role`. */
function allows(
  roleRanks: Record<string, number>,
  roleRank: number | null,
  role: string | undefined,
): boolean {
  if (roleRank === null) {
    return false;
  }
  if (role === undefined) {
    return true; // any authenticated user
  }
  const required = roleRanks[role];
  return required !== undefined && roleRank >= required;
}

function DefaultUnauthorized() {
  return <p>{useStrings().unauthorized}</p>;
}

/**
 * Build a TanStack Router from module manifests. The root route renders the {@link AppShell}
 * (logo + title brand, a role-filtered icon/label sidebar of TanStack `Link`s, the
 * {@link UserMenu} pinned at the sidebar's bottom, the sticky header with the sidebar
 * toggle and theme/language controls, and the footer) around an `<Outlet/>`; each manifest
 * route mounts its `view`, gated by the route's `role` (an unknown role is denied). The
 * built-in {@link ProfileView} mounts at {@link PROFILE_PATH} unless a manifest claims that
 * path. Wrap the returned router in `<TerpProvider><RouterProvider router={router}/></TerpProvider>`.
 */
export function buildAppRouter(
  manifests: readonly ModuleManifest[],
  options: BuildAppRouterOptions,
) {
  const roleRanks = options.roleRanks ?? DEFAULT_ROLE_RANKS;
  const Unauthorized = options.unauthorized ?? DefaultUnauthorized;
  const layoutContract = options.layoutContract ?? null;
  if (layoutContract !== null && LAYOUT_CONTRACTS[layoutContract] === undefined) {
    throw new Error(
      `Unknown layout contract "${layoutContract}"; known contracts: ` +
        Object.keys(LAYOUT_CONTRACTS).join(", ") +
        ".",
    );
  }
  // An authoring error with no legitimate transient form, so it is refused here rather than
  // absorbed. `groupNav` itself stays total — first declaration wins — because it runs on every
  // render and a render must not be able to throw; this runs once, when the app is composed.
  // Deliberately NOT symmetrical with an item naming an undeclared group, which is not an error
  // at all: a module ships on its own schedule, so that is the normal state of an app mid-adoption
  // and it falls open.
  const duplicateGroups = (options.navGroups ?? [])
    .map((group) => group.id)
    .filter((id, index, ids) => ids.indexOf(id) !== index);
  if (duplicateGroups.length > 0) {
    throw new Error(
      "Terp navGroups declare duplicate id(s): " +
        [...new Set(duplicateGroups)].join(", ") +
        ". Each group id is referenced by NavItem.group and must be declared once.",
    );
  }
  const missingViews = manifests.flatMap((manifest) =>
    manifest.routes
      .filter((route) => options.views[route.view] === undefined)
      .map((route) => `${manifest.name}:${route.path} -> ${route.view}`),
  );
  if (missingViews.length > 0) {
    throw new Error(
      "Terp route(s) reference missing view(s): " + missingViews.join(", "),
    );
  }

  // The runtime half of the search declaration (ADR 0096): the generated table is types
  // only, so `useRouteSearch` reads the keys from the manifests this router was built from,
  // published per router through a context (never a module-level table, which every router
  // in the process would share).
  const searchKeys = new Map(indexSearchKeys(manifests));
  if (!searchKeys.has(PROFILE_PATH)) {
    searchKeys.set(PROFILE_PATH, []);
  }

  function Shell() {
    const router = useRouter();
    const user = useAuth().currentUser();
    const rank = user?.role_rank ?? null;
    const nav = visibleNav(manifests, {
      canSeeRole: (role) => allows(roleRanks, rank, role),
      permissions: user?.permissions ?? [],
    });
    // The shell decides which nav item is current and needs the path to do it. Selected, so the
    // subscription re-renders only when the pathname itself changes — the same mechanism
    // ModuleNav already uses.
    const pathname = useRouterState({ select: (state) => state.location.pathname });
    // Memoised, and this is a fix for a regression the line above introduces rather than
    // tidying. `Shell` used to re-render only when `useAuth()` changed; it now re-renders on
    // every navigation. `Outlet` is memoised with no props, so a re-render alone bails out at
    // that boundary and the routed subtree is untouched — but a CONTEXT VALUE punches straight
    // through a memo bailout, and this value is used as a component (Breadcrumbs and HubCard
    // render it through useNavLink), so an unstable identity is worse than a re-render: it
    // remounts every in-app link in the tree on each navigation.
    const renderNavLink = useCallback<NavLinkRenderer>(
      ({ to, children, attributes }) => (
        <Link to={to} {...attributes}>
          {children}
        </Link>
      ),
      [],
    );
    return (
      // Publish the router's Link so every layout component that renders an in-app link
      // (Breadcrumbs, HubCard) navigates client-side by default. Forgetting `renderLink`
      // used to degrade the app silently: a raw anchor, a full page reload, no error.
      <NavLinkContext.Provider value={renderNavLink}>
      <AppShell
        title={options.title}
        logo={options.logo}
        logoDark={options.logoDark}
        headerActions={options.headerActions}
        footer={options.footer}
        contentWidth={options.contentWidth}
        density={options.density}
        navPlacement={options.navPlacement}
        activePath={pathname}
        nav={nav}
        navGroups={options.navGroups}
        renderBrandLink={({ to, children }) => (
          <Link to={to} data-terp="appshell-brand">
            {children}
          </Link>
        )}
        // No style objects and no activeProps: the shell's stylesheet owns the link geometry
        // and keys the active route on aria-current="page".
        //
        // The shell supplies that attribute now, and `exact: true` is what makes the router
        // agree instead of arguing. Two facts combine. `aria-current` is not among the props
        // useLinkProps destructures, so a value passed here survives into the rendered anchor;
        // and the router's own active props are spread LAST, but only when it considers the link
        // active. With exact matching, "the router considers it active" implies the link's path
        // equals the URL — which is the longest possible match, so it is always the same item
        // the shell picked. The router can therefore only ever agree, never add a second
        // current item.
        //
        // Prefix matching is what broke that: it marked every ancestor active, so `/settings`
        // and `/settings/users` were both current at `/settings/users`. The old
        // `exact: item.to === "/"` was a workaround for the same thing at the root, and it is
        // gone because the shell's predicate matches on segments and `/` claims nothing else.
        renderLink={(item, children, { active }) => (
          <Link
            to={item.to}
            activeOptions={{ exact: true }}
            aria-current={active ? "page" : undefined}
          >
            {children}
          </Link>
        )}
        navFooter={({ collapsed }) => (
          <UserMenu
            collapsed={collapsed}
            onSettings={() => void router.navigate({ to: PROFILE_PATH })}
          />
        )}
      >
        <Outlet />
      </AppShell>
      </NavLinkContext.Provider>
    );
  }

  const rootRoute = createRootRoute({ component: Shell });

  function guardedRoute(
    path: string,
    View: ComponentType,
    declaration: { role?: string; permission?: string },
    viewName: string,
  ): AnyRoute {
    function RouteComponent() {
      const user = useAuth().currentUser();
      const rank = user?.role_rank ?? null;
      // The same resolution the sidebar uses, and using it here is what stops `permission` from
      // becoming a cosmetic gate: hiding a link while leaving its route reachable by URL is not
      // a weaker version of authorization, it is the appearance of it. `role` has never had that
      // asymmetry — it is declared on both NavItem and ModuleRoute — so `permission` does not
      // get to introduce one.
      const allowed = isDeclarationVisible(declaration, {
        canSeeRole: (role) => allows(roleRanks, rank, role),
        permissions: user?.permissions ?? [],
      });
      // The runtime half of the "every routed view is a page archetype" control: Page
      // (composed by OverviewPage / DetailPage / HubPage) marks the render; a routed view
      // that mounted without any archetype in its tree is refused, fail closed. The check
      // waits one macrotask so a view whose archetype lands on a follow-up commit (e.g. a
      // lazy inner component resolving) is not refused spuriously.
      const marked = useRef(false);
      const [unframed, setUnframed] = useState(false);
      useEffect(() => {
        if (!allowed || marked.current) {
          return;
        }
        const timer = setTimeout(() => {
          if (!marked.current) {
            setUnframed(true);
          }
        }, 0);
        return () => clearTimeout(timer);
      }, [allowed]);
      if (unframed && !marked.current) {
        throw new Error(
          `Terp routed view "${viewName}" must render a react-core page archetype ` +
            "(Page, OverviewPage, DetailPage or HubPage) so every screen keeps the " +
            "breadcrumb/title/error frame.",
        );
      }
      if (!allowed) {
        return <Unauthorized />;
      }
      return (
        <RouteSearchContext.Provider value={searchKeys}>
          <LayoutContractContext.Provider value={layoutContract}>
            <PageMarkerContext.Provider
              value={() => {
                marked.current = true;
              }}
            >
              <View />
            </PageMarkerContext.Provider>
          </LayoutContractContext.Provider>
        </RouteSearchContext.Provider>
      );
    }
    return createRoute({
      getParentRoute: () => rootRoute,
      path: routerPath(path),
      component: RouteComponent,
    });
  }

  const childRoutes: AnyRoute[] = manifests.flatMap((manifest) =>
    manifest.routes.map((route) =>
      guardedRoute(route.path, options.views[route.view]!, route, route.view),
    ),
  );
  const profileClaimed = manifests.some((manifest) =>
    manifest.routes.some((route) => route.path === PROFILE_PATH),
  );
  if (!profileClaimed) {
    childRoutes.push(guardedRoute(PROFILE_PATH, ProfileView, {}, "profile"));
  }

  const routeTree = rootRoute.addChildren(childRoutes);
  return createRouter({ routeTree, history: options.history });
}
