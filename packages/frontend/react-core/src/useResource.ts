import { useCallback, useEffect, useRef, useState } from "react";

/** An async collection: the loaded rows plus loading/error state, a reload, and a create-then-reload. */
export interface Resource<T, TCreate> {
  /** The loaded rows (empty until the first load resolves). */
  items: T[];
  /**
   * How many rows match the query in total, when the source said -- `undefined` when it
   * did not, which is not the same as zero and must not be rendered as one.
   *
   * The backend has always sent it: the `Page` envelope is `{items, total, skip, limit}`.
   * The documented recipe for `list` unwrapped `.items` and dropped the rest, so every
   * "showing N of M" and every "at least N" warning was left to re-derive an answer the
   * server had computed -- usually as `items.length >= limit`, which is a heuristic
   * standing in for a number.
   *
   * Optional because the cursor envelope computes it only when the caller asks
   * (`include_total=true`), so "unknown" is a real and common answer rather than a gap.
   * A screen that cannot tell the difference should say "N shown", not "N of 0".
   */
  total?: number;
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

/**
 * A server page as the backend's own envelope shapes it: rows plus how many there are.
 *
 * Deliberately structural rather than an import from the generated client — react-core
 * has no contract dependency, and this has to describe an app's client as readily as the
 * framework's own.
 */
export interface ResourcePage<T> {
  items: T[];
  /** Absent when the server was not asked to count; never 0 standing in for unknown. */
  total?: number;
}

/** How a module fetches (and optionally creates) its rows — typically typed contract-client calls. */
export interface ResourceSource<T, TCreate> {
  /**
   * Fetch the current rows -- either the rows alone, or the page the server sent.
   *
   * `(await client.GET("/api/v1/notes/", {})).data?.items ?? []` still works and still
   * means what it did. Returning the page instead
   * (`(await client.GET(...)).data ?? { items: [] }`) additionally carries `total`
   * through to {@link Resource.total}, because the envelope already has it.
   *
   * A union rather than a second method: one call site, one decision, and every existing
   * source keeps compiling. `Array.isArray` tells the two apart at runtime, which is
   * exact -- a page is an object and rows are an array, with nothing in between.
   */
  list: () => Promise<T[] | ResourcePage<T>>;
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
  const [total, setTotal] = useState<number | undefined>(undefined);
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
      const answer = await sourceRef.current.list();
      // Rows alone leave the total unknown rather than zero: a source that does not
      // report one has said nothing about how many there are, and a screen that reads
      // `undefined` as 0 announces an empty result set over a full page of rows.
      setItems(Array.isArray(answer) ? answer : answer.items);
      setTotal(Array.isArray(answer) ? undefined : answer.total);
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

  return { items, total, loading, error, cause, reload, create, mutate };
}
