import type {
  DataViewQuery,
  DataViewRepository,
  DataViewResult,
} from "../types";

/**
 * How {@link InMemoryDataViewRepository} reads and matches rows.
 *
 * `TField` is the union of field names `getValue` understands. Annotate getValue's
 * field parameter (`(row, field: keyof Ticket & string) => row[field]`) and
 * `searchFields` is checked against it at compile time — without the annotation a
 * misspelled entry resolves to `undefined` for every row, so search silently never
 * matches it (no error at any layer). Leaving the parameter untyped keeps today's
 * unchecked `string` behavior.
 */
export interface InMemoryDataViewRepositoryOptions<T, TField extends string = string> {
  /** Stable row identity. */
  getRowId: (row: T) => string;
  /** The raw sortable/filterable value of a column for a row. */
  getValue: (row: T, columnId: TField) => unknown;
  /**
   * Column ids the free-text search matches against (case-insensitive substring).
   * Omit to disable search (`capabilities.search` becomes false). Checked against
   * getValue's declared field union (`NoInfer` keeps a typo here from widening it).
   */
  searchFields?: NoInfer<TField>[];
  /**
   * Custom filter match; the default is faceted equality (`value` is the filter value or,
   * when an array, any-of).
   */
  matchesFilter?: (row: T, columnId: TField, value: unknown) => boolean;
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
 *   // Annotating the field parameter makes searchFields compile-checked.
 *   getValue: (t, col: keyof Ticket & string) => t[col],
 *   searchFields: ["title", "assignee"],
 * });
 * ```
 */
export class InMemoryDataViewRepository<T, TField extends string = string>
  implements DataViewRepository<T>
{
  readonly capabilities: DataViewRepository<T>["capabilities"];

  private rows: T[];
  private readonly options: InMemoryDataViewRepositoryOptions<T, TField>;

  constructor(rows: T[], options: InMemoryDataViewRepositoryOptions<T, TField>) {
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

  /**
   * Query ids arrive as plain strings ({@link DataViewQuery} is column-agnostic); the
   * `TField` union is an authoring-time contract for the options, so the one narrowing
   * lives here rather than at every call site. (Deliberately not named `valueOf` —
   * that shadows `Object.prototype.valueOf`, which JS calls with no arguments.)
   */
  private fieldValue(row: T, columnId: string): unknown {
    return this.options.getValue(row, columnId as TField);
  }

  /** Distinct values of one column across the full (unfiltered) data set. */
  getFacetedValues(columnId: string): unknown[] {
    const seen = new Set<unknown>();
    for (const row of this.rows) {
      seen.add(this.fieldValue(row, columnId));
    }
    return [...seen];
  }

  query(q: DataViewQuery): Promise<DataViewResult<T>> {
    let result = this.rows;

    for (const filter of q.filters) {
      result = result.filter((row) => {
        if (this.options.matchesFilter !== undefined) {
          return this.options.matchesFilter(row, filter.id as TField, filter.value);
        }
        return defaultMatchesFilter(this.fieldValue(row, filter.id), filter.value);
      });
    }

    const search = q.search.trim().toLowerCase();
    const searchFields = this.options.searchFields ?? [];
    if (search !== "" && searchFields.length > 0) {
      result = result.filter((row) =>
        searchFields.some((field) =>
          String(this.fieldValue(row, field) ?? "")
            .toLowerCase()
            .includes(search),
        ),
      );
    }

    if (q.sorting.length > 0) {
      result = [...result].sort((a, b) => {
        for (const sort of q.sorting) {
          const order = compareValues(
            this.fieldValue(a, sort.id),
            this.fieldValue(b, sort.id),
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
