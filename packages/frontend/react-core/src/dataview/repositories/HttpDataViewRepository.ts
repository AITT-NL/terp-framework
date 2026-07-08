import type {
  DataViewQuery,
  DataViewRepository,
  DataViewResult,
} from "../types";

/**
 * The request seam of {@link HttpDataViewRepository}: given already-mapped API
 * parameters, perform the request (typically via the app's typed contract client)
 * and return one raw page. Injecting it keeps the repository transport-agnostic —
 * any REST/GraphQL backend plugs in without touching DataView.
 */
export type HttpRequestAdapter<T> = (
  params: HttpDataViewParams,
  signal?: AbortSignal,
) => Promise<{ items: T[]; total: number }>;

/** The flat API parameters an {@link HttpRequestAdapter} receives. */
export interface HttpDataViewParams {
  /** `pageIndex * pageSize`. */
  skip: number;
  /** `pageSize`. */
  limit: number;
  /** e.g. `["title", "-created_at"]` (leading `-` = descending). */
  sort: string[];
  /** Column filters keyed by column id. */
  filters: Record<string, unknown>;
  /** Free-text search term ("" when inactive). */
  search: string;
  /** The broadened "search everything" flag. */
  searchBroadened: boolean;
}

export interface HttpDataViewRepositoryOptions<T> {
  /** Performs the actual request from mapped parameters. */
  request: HttpRequestAdapter<T>;
  /** Stable row identity. */
  getRowId: (row: T) => string;
  /** Whether the backend supports free-text search (default true). */
  search?: boolean;
  /** Whether the backend supports the broadened search scope (default false). */
  searchScope?: boolean;
  /**
   * The largest `limit` ever sent (default 200 — Terp's `PAGINATION_MAX_LIMIT`
   * default, which the backend enforces with a 422). An embedded DataView asks its
   * repository for "everything"; against a server-side source that request is
   * clamped here so it degrades to the first `maxLimit` rows instead of failing.
   * Raise it only in lockstep with the backend setting.
   */
  maxLimit?: number;
}

/**
 * A server-side {@link DataViewRepository}: maps every {@link DataViewQuery} to flat
 * API parameters (`skip = pageIndex * pageSize`, `limit = pageSize`, sort/filter/search)
 * and delegates the transport to an injectable {@link HttpRequestAdapter}.
 *
 * @example
 * ```ts
 * const repo = new HttpDataViewRepository<NoteRead>({
 *   getRowId: (n) => n.id,
 *   request: async ({ skip, limit }, signal) => {
 *     const page = unwrap(await client.GET("/api/v1/notes/", {
 *       params: { query: { skip, limit } }, signal,
 *     }));
 *     return { items: page.items, total: page.total };
 *   },
 * });
 * ```
 */
export class HttpDataViewRepository<T> implements DataViewRepository<T> {
  readonly capabilities: DataViewRepository<T>["capabilities"];

  private readonly options: HttpDataViewRepositoryOptions<T>;

  constructor(options: HttpDataViewRepositoryOptions<T>) {
    this.options = options;
    this.capabilities = {
      serverSide: true,
      search: options.search ?? true,
      searchScope: options.searchScope ?? false,
    };
  }

  getRowId(row: T): string {
    return this.options.getRowId(row);
  }

  async query(q: DataViewQuery, signal?: AbortSignal): Promise<DataViewResult<T>> {
    const filters: Record<string, unknown> = {};
    for (const filter of q.filters) {
      filters[filter.id] = filter.value;
    }
    // Clamp the page size first and window with the clamped value, so page N is
    // always the N-th `pageSize` window — never a far-flung skip with a smaller limit.
    const pageSize = Math.min(q.pagination.pageSize, this.options.maxLimit ?? 200);
    const page = await this.options.request(
      {
        skip: q.pagination.pageIndex * pageSize,
        limit: pageSize,
        sort: q.sorting.map((sort) => (sort.desc ? `-${sort.id}` : sort.id)),
        filters,
        search: q.search,
        searchBroadened: q.searchBroadened,
      },
      signal,
    );
    return { rows: page.items, totalCount: page.total };
  }
}
