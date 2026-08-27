import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import type { ComponentType, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import type { ModuleManifest, NavGroup, UiText } from "@terpjs/contract";

import { LoginView } from "./LoginView";
import type { DevCredentials } from "./LoginView";
import { RequireAuth } from "./RequireAuth";
import { TerpProvider } from "./TerpProvider";
import { AdminHub } from "./admin/AdminHub";
import { adminModule } from "./admin/module";
import { resolveLayoutDeclaration } from "./layoutDeclaration";
import type { LayoutDeclaration } from "./layoutDeclaration";
import { LocaleProvider } from "./locale";
import { installPreviewBridge } from "./previewBridge";
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
  title: UiText;
  /** Discovered modules from an import.meta.glob over "./modules/<name>/module.tsx" (eager). */
  modules: Record<string, unknown>;
  /** Brand mark in the sidebar (any rendered node); default: the placeholder TerpMark. */
  logo?: ReactNode;
  /**
   * The dark-theme brand mark ({@link AppShell.logoDark}); the stylesheet picks per appearance,
   * with no code of the app's involved.
   *
   * Forwarded because it was not, and the template already told every new app to pass it — so
   * the documented example did not typecheck. Third instance of the shape this ADR's Context
   * names for `headerActions`: a slot that exists on the shell and cannot be reached from the
   * one-call bootstrap.
   */
  logoDark?: ReactNode;
  /**
   * Extra header content, rendered before the theme / language controls.
   *
   * `AppShell` has had this slot all along and `renderTerpApp` did not pass it, so the only way
   * to reach it was to abandon the one-call bootstrap for `TerpProvider` + `buildAppRouter` —
   * a slot that existed and was unreachable from the entry point every app uses.
   */
  headerActions?: ReactNode;
  /** Footer line under the content; default: a muted line with the app title. */
  footer?: ReactNode;
  /**
   * Cap routed content at the published measure, with each page's header on the full track
   * ({@link AppShell.contentWidth}); default `"full"`, which changes nothing. Move the measure
   * itself from an app's own `theme.css`: `--shell-content-max-width`.
   */
  contentWidth?: "full" | "measured";
  /**
   * App-wide density — one attribute on the shell root, from which every control height and cell
   * padding follows by token inheritance.
   *
   * **No default.** Omitting it stamps nothing, so an app setting `data-density` on `<html>`
   * (ADR 0094 §4's app-wide case) still reaches everything; a shell default would silently win
   * against it.
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
   * The app's navigation groups ({@link AppShell.navGroups}), referenced by manifest items
   * through `NavItem.group`. Omit for the flat, unlabelled sidebar every app renders today.
   *
   * This is the app's half of the model and there is no module-side equivalent: a group spans
   * modules, so its label and its position cannot belong to any one of them. A duplicate id is
   * refused when the router is built.
   *
   * Prefer {@link RenderTerpAppOptions.layout}: `shell.navGroups` in the app's own
   * `frontend/layout-contract.json` says the same thing in the one document a tool can read and
   * rewrite. Declaring the groups in both places is refused rather than silently resolved.
   */
  navGroups?: readonly NavGroup[];
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
  /** Source locale for app-authored UiText descriptors; default: the first locale key. */
  sourceLocale?: string;
  /**
   * Starting theme when the user has not chosen one; default `"system"` (OS preference).
   *
   * Prefer {@link RenderTerpAppOptions.layout}: `"defaultTheme"` in the app's own
   * `frontend/layout-contract.json` says the same thing in the one document a tool can read and
   * rewrite, which is the whole reason the declaration exists. Declaring it in both places is
   * refused rather than silently resolved.
   */
  defaultTheme?: Theme;
  /**
   * Opt into a slot-typed layout contract (ADR 0079), e.g. `"standard"`: every routed
   * archetype's body slot then accepts only the components the contract allows there,
   * verified at runtime (fail closed).
   *
   * Prefer {@link RenderTerpAppOptions.layout} — importing the app's own
   * `frontend/layout-contract.json` declares this once for both halves. This option used to
   * carry the instruction "keep it in sync with the checked-in file", which is a defect
   * written as advice: the lint rule reads the file, this read the option, and nothing
   * compared them.
   */
  layoutContract?: string;
  /**
   * The app's checked-in layout declaration: `import layout from "../layout-contract.json"`.
   *
   * One file declaring the layout contract for both the lint rule and the runtime check, plus
   * the palette the app opens on and the shell's own shape — density, navigation placement,
   * content measure, and the navigation groups a module's items name by id. Declaring a key
   * here and passing the matching option is refused rather than silently resolved.
   *
   * The authoritative list is `TOP_LEVEL_KEYS` and `SHELL_KEYS` in
   * {@link ./layoutDeclaration}, and the published `layout.manifest.json` beside them. This
   * sentence is a restatement and has already drifted once.
   */
  layout?: LayoutDeclaration;
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
  // Resolved here as well as inside `buildAppRouter`, because the one key mounted OUTSIDE the
  // router is the palette: `ThemeProvider` wraps everything, the router included.
  //
  // Two calls, one answer — but only while both are handed the SAME option set, and that is a
  // standing obligation rather than something the code enforces. It was broken once already,
  // within a day: `navGroups` was added to the router's set and not to this one, so a groups
  // conflict declared through `renderTerpApp` was invisible here and the resolver's
  // report-every-conflict-at-once property quietly became report-some. Anything added to
  // `BuildAppRouterOptions` and passed at the bottom of this function belongs in this call too;
  // `bootstrap.test.tsx` names both conflicts in one message to hold that.
  //
  // `layout` and every option still go down untouched, so a key added to the declaration later
  // reaches the router without being threaded through this function first.
  const layout = resolveLayoutDeclaration(options.layout, {
    contract: options.layoutContract,
    density: options.density,
    navPlacement: options.navPlacement,
    contentWidth: options.contentWidth,
    navGroups: options.navGroups,
    defaultTheme: options.defaultTheme,
  });
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
    logoDark: options.logoDark,
    headerActions: options.headerActions,
    footer: options.footer,
    contentWidth: options.contentWidth,
    density: options.density,
    navPlacement: options.navPlacement,
    navGroups: options.navGroups,
    layoutContract: options.layoutContract,
    layout: options.layout,
  });
  const root = options.rootElement ?? document.getElementById("root");
  if (!root) {
    throw new Error('renderTerpApp: no root element (add <div id="root"> or pass rootElement).');
  }
  // The channel a tool showing this app in an iframe can ask it questions through, and it exists
  // ONLY in a development build: `import.meta.env.DEV` folds to false in production and the
  // module goes with it, so a deployed app carries no listener at all. Same mechanism, and the
  // same reason, as the template's dev sign-in credentials. See ./previewBridge.
  if (import.meta.env.DEV) {
    installPreviewBridge();
  }
  createRoot(root).render(
    <StrictMode>
      <ThemeProvider defaultTheme={layout.defaultTheme}>
        <LocaleProvider
          locales={options.locales ?? { en: {} }}
          defaultLocale={options.defaultLocale}
          sourceLocale={options.sourceLocale}
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
