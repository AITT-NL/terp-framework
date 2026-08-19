import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  useNavigate,
  useParams,
  useRouter,
  type AnyRoute,
  type RouterHistory,
} from "@tanstack/react-router";
import type { ComponentType, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type { ModuleManifest } from "@terpjs/contract";

import { AppShell } from "./AppShell";
import { ProfileView } from "./ProfileView";
import type {
  TerpNavigateTarget,
  TerpRouteParamName,
  TerpRouteParams,
  TerpRoutePath,
} from "./routeTypes";
import { LAYOUT_CONTRACTS, LayoutContractContext } from "./layoutContract";
import { visibleNav } from "./nav";
import { NavLinkContext } from "./navLink";
import { PageMarkerContext } from "./pageMarker";
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
    });
}

export interface BuildAppRouterOptions {
  /** Maps a manifest route's `view` id to the component that renders it. */
  views: Record<string, ComponentType>;
  /** App title shown in the shell's sidebar brand. */
  title: string;
  /** Brand mark in the sidebar (any rendered node); default: the placeholder TerpMark. */
  logo?: ReactNode;
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
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

  function Shell() {
    const router = useRouter();
    const rank = useAuth().currentUser()?.role_rank ?? null;
    const nav = visibleNav(manifests, (role) => allows(roleRanks, rank, role));
    return (
      // Publish the router's Link so every layout component that renders an in-app link
      // (Breadcrumbs, HubCard) navigates client-side by default. Forgetting `renderLink`
      // used to degrade the app silently: a raw anchor, a full page reload, no error.
      <NavLinkContext.Provider value={({ to, children }) => <Link to={to}>{children}</Link>}>
      <AppShell
        title={options.title}
        logo={options.logo}
        footer={options.footer}
        nav={nav}
        renderBrandLink={({ to, children }) => (
          <Link to={to} data-terp="appshell-brand">
            {children}
          </Link>
        )}
        // No style objects and no activeProps: the shell's stylesheet owns the link
        // geometry and keys the active route on aria-current="page", which Link sets.
        renderLink={(item, children) => (
          <Link to={item.to} activeOptions={{ exact: item.to === "/" }}>
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
    role: string | undefined,
    viewName: string,
  ): AnyRoute {
    function RouteComponent() {
      const rank = useAuth().currentUser()?.role_rank ?? null;
      const allowed = allows(roleRanks, rank, role);
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
        <LayoutContractContext.Provider value={layoutContract}>
          <PageMarkerContext.Provider
            value={() => {
              marked.current = true;
            }}
          >
            <View />
          </PageMarkerContext.Provider>
        </LayoutContractContext.Provider>
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
      guardedRoute(route.path, options.views[route.view]!, route.role, route.view),
    ),
  );
  const profileClaimed = manifests.some((manifest) =>
    manifest.routes.some((route) => route.path === PROFILE_PATH),
  );
  if (!profileClaimed) {
    childRoutes.push(guardedRoute(PROFILE_PATH, ProfileView, undefined, "profile"));
  }

  const routeTree = rootRoute.addChildren(childRoutes);
  return createRouter({ routeTree, history: options.history });
}
