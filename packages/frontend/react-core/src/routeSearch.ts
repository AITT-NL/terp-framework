import { createContext, useContext } from "react";

import type { ModuleManifest } from "@terpjs/contract";

/**
 * The runtime half of a route's declared query-string keys (ADR 0096).
 *
 * The generated `routes.gen.d.ts` is types only — it vanishes at runtime — so
 * `useRouteSearch` needs the same declarations as data. They come from the manifests the
 * router was built from, published through a context rather than a module-level table:
 * a table would be shared by every router composed in one process, so an app embedding
 * another (or a test file composing two) would read declarations it never mounted.
 */
export const RouteSearchContext = createContext<ReadonlyMap<string, readonly string[]> | null>(
  null,
);

/** The manifest spelling (`:id`), so a `$id` manifest and a `:id` read agree on one key. */
export function canonicalRoutePath(path: string): string {
  return path.replace(/(^|\/)\$([A-Za-z_][A-Za-z0-9_]*)/g, "$1:$2");
}

/**
 * Index every manifest route's declared search keys by its canonical path.
 *
 * Two manifests mounting one path union their keys, matching what the generator emits into
 * the type table — so the runtime read and the compile-time check agree.
 */
export function indexSearchKeys(
  manifests: readonly ModuleManifest[],
): ReadonlyMap<string, readonly string[]> {
  const index = new Map<string, readonly string[]>();
  for (const manifest of manifests) {
    for (const route of manifest.routes) {
      const key = canonicalRoutePath(route.path);
      index.set(key, [...new Set([...(index.get(key) ?? []), ...(route.search ?? [])])]);
    }
  }
  return index;
}

/**
 * The search keys declared for *path*, or a refusal naming what is mounted.
 *
 * A path the router never mounted is a programming error, not an empty result: returning
 * `{}` would hand a screen `undefined` for every key it asked for, which reads as "no
 * filters applied" — the silent-wrong-answer this refusal replaces.
 */
export function declaredSearchKeys(
  index: ReadonlyMap<string, readonly string[]> | null,
  path: string,
): readonly string[] {
  if (index === null) {
    throw new Error(
      `useRouteSearch("${path}") was called outside a Terp router. It reads the declarations ` +
        "the router was built from, so it only works under a view mounted by buildAppRouter.",
    );
  }
  const declared = index.get(canonicalRoutePath(path));
  if (declared === undefined) {
    throw new Error(
      `Route "${path}" is not a mounted route, so its search keys are unknown (mounted: ` +
        `${[...index.keys()].join(", ") || "none"}). useRouteSearch takes the path as written ` +
        "in the module manifest — check it there, and run `terp routes` if the manifest changed.",
    );
  }
  return declared;
}

/** The mounted routes' search-key index, or null outside a Terp router. */
export function useRouteSearchIndex(): ReadonlyMap<string, readonly string[]> | null {
  return useContext(RouteSearchContext);
}
