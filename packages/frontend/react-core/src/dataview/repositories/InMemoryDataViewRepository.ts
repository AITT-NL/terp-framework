import type {
  DataViewQuery,
  DataViewRepository,
  DataViewResult,
} from "../types";

/** How {@link InMemoryDataViewRepository} reads and matches rows. */
export interface InMemoryDataViewRepositoryOptions<T> {
  /** Stable row identity. */
  getRowId: (row: T) => string;
  /** The raw sortable/filterable value of a column for a row. */
  getValue: (row: T, columnId: string) => unknown;
  /**
   * Column ids the free-text search matches against (case-insensitive substring).
   * Omit to disable search (`capabilities.search` becomes false).
   */
  searchFields?: string[];
  /**
   * Custom filter match; the default is faceted equality (`value` is the filter value or,
   * when an array, any-of).
   */
  matchesFilter?: (row: T, columnId: string, value: unknown) => boolean;
}

function defaultMatchesFilter(cell: unknown, value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.length === 0 || value.some((candidate) => candidate === cell);
  }
  return cell === value;
}

function compareValues(a: unknown, b: unknown): number {
  if (a === b) {
    return 0;
  }
  if (a === null || a === undefined) {
    return -1;
  }
  if (b === null || b === undefined) {
    return 1;
  }
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  if (a instanceof Date && b instanceof Date) {
    return a.getTime() - b.getTime();
  }
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * A {@link DataViewRepository} over a plain array: filtering, searching, sorting and
 * paging all happen client-side inside the repository, so the DataView stays a pure
 * renderer of {@link DataViewResult} pages.
 *
 * @example
 * ```ts
 * const repo = new InMemoryDataViewRepository(tickets, {
 *   getRowId: (t) => t.id,
 *   getValue: (t, col) => t[col as keyof Ticket],
 *   searchFields: ["title", "assignee"],
 * });
 * ```
 */
export class InMemoryDataViewRepository<T> implements DataViewRepository<T> {
  readonly capabilities: DataViewRepository<T>["capabilities"];

  private rows: T[];
  private readonly options: InMemoryDataViewRepositoryOptions<T>;

  constructor(rows: T[], options: InMemoryDataViewRepositoryOptions<T>) {
    this.rows = rows;
    this.options = options;
    this.capabilities = {
      serverSide: false,
      search: (options.searchFields ?? []).length > 0,
      searchScope: false,
    };
  }

  getRowId(row: T): string {
    return this.options.getRowId(row);
  }

  /** Replace the backing rows (e.g. after a caller-side refetch). */
  setRows(rows: T[]): void {
    this.rows = rows;
  }

  /** Distinct values of one column across the full (unfiltered) data set. */
  getFacetedValues(columnId: string): unknown[] {
    const seen = new Set<unknown>();
    for (const row of this.rows) {
      seen.add(this.options.getValue(row, columnId));
    }
    return [...seen];
  }

  query(q: DataViewQuery): Promise<DataViewResult<T>> {
    let result = this.rows;

    for (const filter of q.filters) {
      result = result.filter((row) => {
        if (this.options.matchesFilter !== undefined) {
          return this.options.matchesFilter(row, filter.id, filter.value);
        }
        return defaultMatchesFilter(this.options.getValue(row, filter.id), filter.value);
      });
    }

    const search = q.search.trim().toLowerCase();
    const searchFields = this.options.searchFields ?? [];
    if (search !== "" && searchFields.length > 0) {
      result = result.filter((row) =>
        searchFields.some((field) =>
          String(this.options.getValue(row, field) ?? "")
            .toLowerCase()
            .includes(search),
        ),
      );
    }

    if (q.sorting.length > 0) {
      result = [...result].sort((a, b) => {
        for (const sort of q.sorting) {
          const order = compareValues(
            this.options.getValue(a, sort.id),
            this.options.getValue(b, sort.id),
          );
          if (order !== 0) {
            return sort.desc ? -order : order;
          }
        }
        return 0;
      });
    }

    const totalCount = result.length;
    const start = q.pagination.pageIndex * q.pagination.pageSize;
    return Promise.resolve({
      rows: result.slice(start, start + q.pagination.pageSize),
      totalCount,
    });
  }
}
