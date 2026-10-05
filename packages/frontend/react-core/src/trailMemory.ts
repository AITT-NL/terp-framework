import { createContext, useContext } from "react";

/**
 * What the breadcrumb trail has already said about each place, for as long as the app runs
 * (ADR 0173).
 *
 * Every routed view mounts its own page, so the trail is built again on every navigation, and
 * a label that comes from data (a record's name) is not known again until that data is: the
 * trail used to print a stand-in and then the name, on every visit, on every tab of a detail,
 * and on the parent crumb one level down. The trail is the same place it was a moment ago, so
 * it can say so. A crumb whose label is not known yet shows the last label it had at that
 * path, and only a place never seen before shows a placeholder.
 *
 * The router's shell holds the labels, one map for the app's lifetime ({@link TrailLabelsContext}),
 * and each routed view binds them to the path ITS OWN match is at. Not the router's current
 * location: during a navigation the old page is still rendered while the location is already
 * the new one, so a leaf keyed by the location remembered the page being left under the name of
 * the page being opened, and the detail then recalled its parent's title. A trail outside a Terp
 * router has no memory: a pending crumb is a placeholder there, and nothing else changes.
 */
export interface TrailMemory {
  /** The path this routed view's own match is at: the key for its leaf, which has no `to`. */
  readonly pathname: string;
  /** The last label shown at *path*, if any. */
  recall(path: string): string | undefined;
  /** Remember *label* as what *path* is called. */
  remember(path: string, label: string): void;
}

/** One spelling per place: no query, no fragment, no trailing slash past the root. */
export function trailPath(path: string): string {
  const bare = path.split(/[?#]/, 1)[0]!;
  return bare.length > 1 ? bare.replace(/\/+$/, "") : bare;
}

/** A memory over *labels*, at *pathname*. The map outlives the value, which a navigation replaces. */
export function trailMemory(labels: Map<string, string>, pathname: string): TrailMemory {
  return {
    pathname,
    recall: (path) => labels.get(trailPath(path)),
    remember: (path, label) => {
      labels.set(trailPath(path), label);
    },
  };
}

/** The labels themselves, held by the router's shell across every navigation. */
export const TrailLabelsContext = createContext<Map<string, string> | null>(null);

/** The memory bound to the routed view's own path. */
export const TrailMemoryContext = createContext<TrailMemory | null>(null);

/** The surrounding router's trail memory, or `null` outside one. */
export function useTrailMemory(): TrailMemory | null {
  return useContext(TrailMemoryContext);
}
