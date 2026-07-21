import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import type { ComponentType, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import type { ModuleManifest } from "@terp/contract";

import { LoginView } from "./LoginView";
import type { DevCredentials } from "./LoginView";
import { RequireAuth } from "./RequireAuth";
import { TerpProvider } from "./TerpProvider";
import { AdminHub } from "./admin/AdminHub";
import { adminModule } from "./admin/module";
import { LocaleProvider } from "./locale";
import type { LocaleCatalog } from "./locale";
import { buildAppRouter } from "./router";
import type { SsoProvider } from "./sso";
import { ThemeProvider } from "./theme";
import type { Theme } from "./theme";
import { ToastProvider } from "./toast";

/** A frontend module: its stack-agnostic manifest and the view components it names. */
export interface TerpModule {
  manifest: ModuleManifest;
  views: Record<string, ComponentType>;
}

/**
 * Which packaged admin screens to ship — one flag per backend capability the area
 * fronts. Omitted flags default to `true`, so `{ groups: false }` is the whole
 * "users + audit without groups" configuration: the groups routes, hub card and
 * stat call disappear while the rest of the area stays packaged.
 */
export interface AdminAreaSections {
  /** The users overview / create / detail screens (terp-cap-users). */
  users?: boolean;
  /** The groups overview / create / detail screens (terp-cap-groups). */
  groups?: boolean;
  /** The audit-log overview (terp-cap-audit). */
  audit?: boolean;
}

/** Route-path prefix per admin section, used to filter the packaged manifest. */
const ADMIN_SECTION_PREFIXES: Record<keyof AdminAreaSections, string> = {
  users: "/admin/users",
  groups: "/admin/groups",
  audit: "/admin/audit",
};

function resolveAdminSections(
  config: boolean | AdminAreaSections,
): Required<AdminAreaSections> {
  const sections = typeof config === "boolean" ? {} : config;
  return {
    users: sections.users !== false,
    groups: sections.groups !== false,
    audit: sections.audit !== false,
  };
}

function isTerpModule(value: unknown): value is TerpModule {
  return (
    typeof value === "object" && value !== null && "manifest" in value && "views" in value
  );
}

/**
 * Merge discovered module files into the manifests + views that build the app router.
 * Pass the result of an import.meta.glob over "./modules/<name>/module.tsx"; each module
 * file must export `manifest` and `views`, so a new module is wired by dropping a
 * folder — no central registry to edit.
 */
export function collectModules(modules: Record<string, unknown>): {
  manifests: ModuleManifest[];
  views: Record<string, ComponentType>;
} {
  const manifests: ModuleManifest[] = [];
  const views: Record<string, ComponentType> = {};
  for (const [path, mod] of Object.entries(modules)) {
    if (!isTerpModule(mod)) {
      throw new Error(`Terp module '${path}' must export \`manifest\` and \`views\`.`);
    }
    manifests.push(mod.manifest);
    for (const [viewId, View] of Object.entries(mod.views)) {
      if (views[viewId] !== undefined) {
        throw new Error(`Terp view '${viewId}' is exported by more than one module.`);
      }
      views[viewId] = View;
    }
  }
  return { manifests, views };
}

export interface RenderTerpAppOptions {
  /** App title shown in the shell's sidebar brand (and the default footer). */
  title: string;
  /** Discovered modules from an import.meta.glob over "./modules/<name>/module.tsx" (eager). */
  modules: Record<string, unknown>;
  /** Brand mark in the sidebar (any rendered node); default: the placeholder TerpMark. */
  logo?: ReactNode;
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
  /**
   * Ship the packaged admin area (default `true`): the admin-gated sidebar entry, the
   * `/admin` hub, and the users / groups / audit screens over the base-profile
   * capabilities. An app route claiming one of its paths overrides that screen;
   * `false` drops the whole area (e.g. an app building its own admin surface).
   * A partial {@link AdminAreaSections} object keeps the area but selects which
   * capability screens it ships — e.g. `{ groups: false }` for a users + audit
   * profile without groups.
   */
  adminArea?: boolean | AdminAreaSections;
  /** Backend API origin; default "" (same-origin, for a dev proxy). */
  baseUrl?: string;
  /** Signed-out screen; default the built-in {@link LoginView}. */
  login?: ReactNode;
  /** SSO providers offered by the default {@link LoginView} (ignored when `login` is set). */
  ssoProviders?: readonly SsoProvider[];
  /**
   * Dev-only fill button on the default {@link LoginView} (ignored when `login` is set).
   * Gate it on the build — `import.meta.env.DEV ? { email, password } : undefined` — so the
   * credentials are statically stripped from production bundles; never pass real secrets.
   */
  devCredentials?: DevCredentials;
  /** SPA path prefix the IdP redirects back to; default "/auth/callback" (ADR 0058). */
  ssoCallbackPath?: string;
  /**
   * The app's locales, keyed by BCP-47 code (default `{ en: LOCALE_EN }`). Each catalog
   * overrides the framework strings for that locale; the built-in {@link UserMenu} offers
   * a language switcher as soon as more than one locale is declared.
   */
  locales?: Record<string, LocaleCatalog>;
  /** Starting locale when the user has not chosen one; default: the first `locales` key. */
  defaultLocale?: string;
  /** Starting theme when the user has not chosen one; default "system" (OS preference). */
  defaultTheme?: Theme;
  /**
   * Opt into a slot-typed layout contract (ADR 0079), e.g. `"standard"`: every routed
   * archetype's body slot then accepts only the components the contract allows there,
   * verified at runtime (fail closed). Keep it in sync with the app's checked-in
   * `layout-contract.json` (the `terp/layout-contract` lint half).
   */
  layoutContract?: string;
  /** Mount point; default `document.getElementById("root")`. */
  rootElement?: HTMLElement | null;
}

/**
 * Merge the packaged admin area into collected modules (the `renderTerpApp` default).
 * Pure and collision-aware: per path the app wins — an app route claiming an admin
 * path drops that packaged screen (mirroring the built-in /profile rule) — and the
 * sidebar's Admin entry disappears with the hub. Disabled (`false`) it returns the
 * inputs untouched; an {@link AdminAreaSections} object keeps the area but ships
 * only the selected capability screens (the hub renders one card per kept section).
 */
export function withAdminArea(
  manifests: ModuleManifest[],
  views: Record<string, ComponentType>,
  config: boolean | AdminAreaSections,
): { manifests: ModuleManifest[]; views: Record<string, ComponentType> } {
  if (config === false) {
    return { manifests, views };
  }
  const sections = resolveAdminSections(config);
  const sectionAllows = (path: string): boolean =>
    (Object.keys(ADMIN_SECTION_PREFIXES) as (keyof AdminAreaSections)[]).every(
      (section) =>
        sections[section] || !path.startsWith(ADMIN_SECTION_PREFIXES[section]),
    );
  const claimed = new Set(
    manifests.flatMap((manifest) => manifest.routes.map((route) => route.path)),
  );
  const routes = adminModule.manifest.routes.filter(
    (route) => !claimed.has(route.path) && sectionAllows(route.path),
  );
  // A view-id collision without a path claim would silently drop a packaged screen
  // the hub still links to — refuse it loudly (claim the path to override a screen,
  // or rename the app view; mirrors collectModules' duplicate-view error).
  const collisions = routes
    .filter((route) => views[route.view] !== undefined)
    .map((route) => route.view);
  if (collisions.length > 0) {
    throw new Error(
      "Terp view id(s) collide with the packaged admin area: " +
        collisions.join(", ") +
        ". Rename the app view(s), claim the admin route path(s) to override the " +
        "screen(s), or disable the area with adminArea: false.",
    );
  }
  if (routes.length === 0) {
    return { manifests, views };
  }
  const merged = { ...views };
  const allSections = sections.users && sections.groups && sections.audit;
  for (const route of routes) {
    if (route.view === "TerpAdminHub" && !allSections) {
      // The hub mirrors the selection: one card per kept section (and no stat
      // call for a dropped one), so a lean profile never dead-links.
      merged[route.view] = function TerpAdminHubSelected() {
        return <AdminHub sections={sections} />;
      };
      continue;
    }
    merged[route.view] = adminModule.views[route.view]!;
  }
  return {
    manifests: [
      ...manifests,
      {
        ...adminModule.manifest,
        routes,
        nav: routes.some((route) => route.path === "/admin")
          ? adminModule.manifest.nav
          : [],
      },
    ],
    views: merged,
  };
}

/**
 * Render a complete Terp app in one call: discover the modules, build the router, and mount
 * the provider + auth gate + shell. A consumer's `main.tsx` is just this plus the token
 * stylesheet import. Drop to `TerpProvider` + `buildAppRouter` for full control.
 */
export function renderTerpApp(options: RenderTerpAppOptions): void {
  const collected = collectModules(options.modules);
  const { manifests, views } = withAdminArea(
    collected.manifests,
    collected.views,
    options.adminArea ?? true,
  );
  const router = buildAppRouter(manifests, {
    views,
    title: options.title,
    logo: options.logo,
    footer: options.footer,
    layoutContract: options.layoutContract,
  });
  const root = options.rootElement ?? document.getElementById("root");
  if (!root) {
    throw new Error('renderTerpApp: no root element (add <div id="root"> or pass rootElement).');
  }
  createRoot(root).render(
    <StrictMode>
      <ThemeProvider defaultTheme={options.defaultTheme}>
        <LocaleProvider
          locales={options.locales ?? { en: {} }}
          defaultLocale={options.defaultLocale}
        >
          <TerpProvider baseUrl={options.baseUrl ?? ""} ssoCallbackPath={options.ssoCallbackPath}>
            <ToastProvider>
              <RequireAuth
                fallback={
                  options.login ?? (
                    <LoginView
                      ssoProviders={options.ssoProviders}
                      devCredentials={options.devCredentials}
                    />
                  )
                }
              >
                <RouterProvider router={router} />
              </RequireAuth>
            </ToastProvider>
          </TerpProvider>
        </LocaleProvider>
      </ThemeProvider>
    </StrictMode>,
  );
}
