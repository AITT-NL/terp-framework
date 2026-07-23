import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  useRouter,
  type AnyRoute,
  type RouterHistory,
} from "@tanstack/react-router";
import type { ComponentType, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type { ModuleManifest } from "@terpjs/contract";

import { AppShell } from "./AppShell";
import { ProfileView } from "./ProfileView";
import { LAYOUT_CONTRACTS, LayoutContractContext } from "./layoutContract";
import { visibleNav } from "./nav";
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
      <AppShell
        title={options.title}
        logo={options.logo}
        footer={options.footer}
        nav={nav}
        renderBrandLink={({ to, children, style }) => (
          <Link to={to} data-terp="appshell-brand" style={style}>
            {children}
          </Link>
        )}
        renderLink={(item, children, context) => (
          <Link
            to={item.to}
            style={context.style}
            activeProps={{ style: { ...context.style, ...context.activeStyle } }}
            activeOptions={{ exact: item.to === "/" }}
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
      path,
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
