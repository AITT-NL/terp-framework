import { useRef } from "react";

import { useResource } from "./useResource";

/** One async record: the loaded row (or `null`) plus loading/error state and a reload. */
export interface RecordResource<T> {
  /** The loaded record, or `null` until the load resolves / when it does not exist. */
  item: T | null;
  /** True while the initial load or a reload is in flight. */
  loading: boolean;
  /** The last error message, or `null` when the most recent load succeeded. */
  error: string | null;
  /**
   * The last caught failure itself, or `null` — typically the `ApiError` thrown by
   * `unwrap`, whose stable `code` lets `useErrorMessage` map it to client-owned copy.
   */
  cause?: unknown;
  /** Re-run the get query. */
  reload: () => Promise<void>;
  /** Run any record-specific mutation (patch, delete, action), surface failures, then reload. */
  mutate: (operation: () => Promise<void>) => Promise<void>;
}

/** How a detail screen fetches its one record — typically a typed contract-client call. */
export interface RecordSource<T> {
  /**
   * Fetch the record. Return `null` for "does not exist and that is a normal state"
   * (compose with `unwrapOptional`); let `unwrap` throw when absence is an error.
   */
  get: () => Promise<T | null>;
}

/**
 * The singleton counterpart of {@link useResource}: the one record a detail screen
 * shows, instead of a collection. Before it existed every detail page spelled the
 * record as a one-element list — `list: async () => [unwrap(await client.GET(...))]`
 * then `items[0]` — a wart this hook deletes wherever detail pages exist.
 *
 * Same contract as `useResource`: `source` may be rebuilt each render (read through a
 * ref), and `deps` (e.g. the route param the query closes over) reloads on in-place
 * navigation between records. Implemented over `useResource` so the two state
 * machines cannot drift.
 */
export function useRecord<T>(
  source: RecordSource<T>,
  deps: readonly unknown[] = [],
): RecordResource<T> {
  const sourceRef = useRef(source);
  sourceRef.current = source;

  const resource = useResource<T | null>(
    { list: async () => [await sourceRef.current.get()] },
    deps,
  );

  return {
    item: resource.items[0] ?? null,
    loading: resource.loading,
    error: resource.error,
    cause: resource.cause,
    reload: resource.reload,
    mutate: resource.mutate,
  };
}
