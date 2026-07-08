import { useCallback, useEffect, useRef, useState } from "react";

/** An async collection: the loaded rows plus loading/error state, a reload, and a create-then-reload. */
export interface Resource<T, TCreate> {
  /** The loaded rows (empty until the first load resolves). */
  items: T[];
  /** True while the initial load or a reload is in flight. */
  loading: boolean;
  /** The last error message, or `null` when the most recent load succeeded. */
  error: string | null;
  /**
   * The last caught failure itself, or `null` — typically the `ApiError` thrown by
   * `unwrap`, whose stable `code` lets `useErrorMessage` map it to client-owned copy.
   * Optional so hand-built `Resource` objects (which predate this field) keep compiling;
   * consumers treat an absent cause the same as `null` (no code-mapped copy).
   */
  cause?: unknown;
  /** Re-run the list query. */
  reload: () => Promise<void>;
  /** Create a row via `source.create`, then reload. Rejects if the resource is read-only. */
  create: (input: TCreate) => Promise<void>;
  /** Run any module-specific mutation (delete, custom action), surface failures, then reload. */
  mutate: (operation: () => Promise<void>) => Promise<void>;
}

/** How a module fetches (and optionally creates) its rows — typically typed contract-client calls. */
export interface ResourceSource<T, TCreate> {
  /** Fetch the current rows (e.g. `(await client.GET("/api/v1/notes/", {})).data?.items ?? []`). */
  list: () => Promise<T[]>;
  /** Optional create (e.g. a typed client POST); omit for a read-only resource. */
  create?: (input: TCreate) => Promise<void>;
}

/**
 * The list + create state machine every module's data hook needs, factored out of the view: it loads
 * once on mount, tracks `loading`/`error`, and exposes `reload` plus a `create` that refreshes the
 * list. Modules wrap it in a typed `useX()` hook (e.g. `useNotes`) that supplies `list`/`create` over
 * the contract client, so views stay declarative and every module fetches the same way.
 *
 * `source` may be rebuilt each render (its callbacks are read through a ref), so a module can pass
 * inline closures without triggering a reload loop. Pass `deps` (e.g. a route param the query
 * closes over) to reload automatically when they change — a detail view keyed by `$id` refreshes
 * on in-place navigation instead of showing the previous record.
 */
export function useResource<T, TCreate = void>(
  source: ResourceSource<T, TCreate>,
  deps: readonly unknown[] = [],
): Resource<T, TCreate> {
  const sourceRef = useRef(source);
  sourceRef.current = source;

  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cause, setCause] = useState<unknown>(null);

  const fail = useCallback((caught: unknown) => {
    setError(caught instanceof Error ? caught.message : String(caught));
    setCause(caught);
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCause(null);
    try {
      setItems(await sourceRef.current.list());
    } catch (caught) {
      fail(caught);
    } finally {
      setLoading(false);
    }
    // The spread keys the loader to caller-declared dependencies (route params etc.).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fail, ...deps]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const mutate = useCallback(
    async (operation: () => Promise<void>) => {
      setError(null);
      setCause(null);
      try {
        await operation();
      } catch (caught) {
        // Surface a failed write (e.g. 403 / 409 / 422) instead of silently no-op'ing, then
        // rethrow so the caller can keep local UI state for a retry.
        fail(caught);
        throw caught;
      }
      await reload();
    },
    [reload, fail],
  );

  const create = useCallback(
    async (input: TCreate) => {
      const createFn = sourceRef.current.create;
      if (!createFn) {
        throw new Error("This resource is read-only (no create was provided).");
      }
      await mutate(() => createFn(input));
    },
    [mutate],
  );

  return { items, loading, error, cause, reload, create, mutate };
}
