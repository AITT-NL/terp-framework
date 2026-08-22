/**
 * Stack-agnostic description of a module's UI surface (design §7.1, item 3).
 *
 * Decision: the manifest *types* are the shared contract (defined here), but each
 * frontend module authors its own manifest *values* — view names and navigation are
 * frontend concerns, so they are not emitted from the backend `ModuleSpec`. Each stack
 * ships a thin adapter that realises a manifest into its own router + sidebar (TanStack
 * Router for React, SvelteKit for Svelte). `role` references the app's backend role
 * names; the stack's auth adapter resolves a name to the backend role rank.
 */

/** A role name as understood by the app's backend (e.g. "viewer" | "editor" | "admin"). */
export type RoleName = string;

export interface ModuleRoute {
  /**
   * URL path the route mounts at, e.g. `/billing` or `/billing/:id`.
   *
   * Parameters are spelled the stack-agnostic way (`:id`) — each adapter translates
   * into its own router's dialect (`$id` for TanStack Router, `[id]` for SvelteKit).
   * The React adapter also accepts `$id` directly, which is what shipped before the
   * translation existed.
   */
  path: string;
  /** Stack-agnostic view identifier the adapter resolves to a component. */
  view: string;
  /** Minimum role required to see the route; omitted = any authenticated user. */
  role?: RoleName;
  /**
   * Query-string keys this route reads, e.g. `["status", "page"]`.
   *
   * Declared for the same reason params are: the router is realised at runtime, so
   * nothing checks a search key either — and a list screen's filters live in the query
   * string, which is why *most* screens were the ones bypassing the typed navigation
   * seam entirely. `terp routes` emits these into the generated table, so navigating
   * with an undeclared key (or reading one) is a typecheck error.
   *
   * Values are `string | undefined` and nothing more: a query parameter is text, and
   * every key is absent until someone sets it. Parsing `page` into a number is the
   * screen's business — declaring the key is what stops it being a typo.
   */
  search?: string[];
}

export interface NavItem {
  /** Sidebar label. */
  label: string;
  /** Destination path; should match a {@link ModuleRoute.path}. */
  to: string;
  /** Icon identifier the stack maps to its own icon set. */
  icon?: string;
  /** Minimum role required to show the nav item. */
  role?: RoleName;
  /**
   * Match the URL exactly rather than as a segment-aligned prefix.
   *
   * The default is the prefix, and that is the useful behaviour: a detail page under a section
   * keeps the section's tab lit, so `/records/123` leaves "Records" current. Set this where a
   * destination should own only itself — typically a landing page that also has children in the
   * nav, where the parent would otherwise stay lit on every child.
   *
   * It does not decide WHICH item is current when several match; that is a property of the set,
   * and the adapter resolves it by longest match. This only says whether this item is a
   * candidate at all.
   */
  exact?: boolean;
}

export interface ModuleManifest {
  /** Module name; matches the backend module / API prefix (e.g. "notes"). */
  name: string;
  routes: ModuleRoute[];
  nav?: NavItem[];
}

/** Identity helper that gives module authors full type-checking on a manifest literal. */
export function defineModuleManifest(manifest: ModuleManifest): ModuleManifest {
  return manifest;
}
