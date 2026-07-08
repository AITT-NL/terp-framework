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
  /** URL path the route mounts at, e.g. "/billing" or "/billing/:id". */
  path: string;
  /** Stack-agnostic view identifier the adapter resolves to a component. */
  view: string;
  /** Minimum role required to see the route; omitted = any authenticated user. */
  role?: RoleName;
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
