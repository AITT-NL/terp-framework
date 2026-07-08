import { describe, expect, it, vi } from "vitest";

import { HttpDataViewRepository } from "./HttpDataViewRepository";
import { InMemoryDataViewRepository } from "./InMemoryDataViewRepository";
import type { DataViewQuery } from "../types";

interface Ticket {
  id: string;
  title: string;
  priority: number;
  status: string;
}

const TICKETS: Ticket[] = [
  { id: "1", title: "Broken printer", priority: 2, status: "open" },
  { id: "2", title: "VPN access", priority: 1, status: "closed" },
  { id: "3", title: "New laptop", priority: 3, status: "open" },
  { id: "4", title: "Password reset", priority: 1, status: "open" },
];

function repo(rows: Ticket[] = TICKETS) {
  return new InMemoryDataViewRepository(rows, {
    getRowId: (t) => t.id,
    getValue: (t, col) => t[col as keyof Ticket],
    searchFields: ["title"],
  });
}

function query(patch: Partial<DataViewQuery> = {}): DataViewQuery {
  return {
    pagination: { pageIndex: 0, pageSize: 10 },
    sorting: [],
    filters: [],
    search: "",
    searchBroadened: false,
    ...patch,
  };
}

describe("InMemoryDataViewRepository", () => {
  it("returns all rows with the total count", async () => {
    const result = await repo().query(query());
    expect(result.rows).toHaveLength(4);
    expect(result.totalCount).toBe(4);
  });

  it("pages with pageIndex/pageSize and keeps the filtered total", async () => {
    const result = await repo().query(query({ pagination: { pageIndex: 1, pageSize: 3 } }));
    expect(result.rows).toHaveLength(1);
    expect(result.totalCount).toBe(4);
  });

  it("sorts ascending and descending", async () => {
    const asc = await repo().query(query({ sorting: [{ id: "priority", desc: false }] }));
    expect(asc.rows.map((t) => t.priority)).toEqual([1, 1, 2, 3]);
    const desc = await repo().query(query({ sorting: [{ id: "title", desc: true }] }));
    expect(desc.rows[0]?.title).toBe("VPN access");
  });

  it("searches case-insensitively across the configured fields", async () => {
    const result = await repo().query(query({ search: "LAPTOP" }));
    expect(result.rows.map((t) => t.id)).toEqual(["3"]);
    expect(result.totalCount).toBe(1);
  });

  it("applies faceted-equality filters (single and any-of)", async () => {
    const single = await repo().query(query({ filters: [{ id: "status", value: "closed" }] }));
    expect(single.rows.map((t) => t.id)).toEqual(["2"]);
    const anyOf = await repo().query(query({ filters: [{ id: "priority", value: [1, 3] }] }));
    expect(anyOf.rows.map((t) => t.id)).toEqual(["2", "3", "4"]);
  });

  it("exposes faceted unique values across the full data set", () => {
    expect(repo().getFacetedValues("status")).toEqual(["open", "closed"]);
  });

  it("advertises client-side capabilities (search only when fields are configured)", () => {
    expect(repo().capabilities).toEqual({ serverSide: false, search: true, searchScope: false });
    const noSearch = new InMemoryDataViewRepository(TICKETS, {
      getRowId: (t) => t.id,
      getValue: (t, col) => t[col as keyof Ticket],
    });
    expect(noSearch.capabilities.search).toBe(false);
  });
});

describe("HttpDataViewRepository", () => {
  it("maps the query to skip/limit/sort/filter/search params", async () => {
    const request = vi.fn().mockResolvedValue({ items: [TICKETS[0]], total: 41 });
    const http = new HttpDataViewRepository<Ticket>({ request, getRowId: (t) => t.id });

    const result = await http.query(
      query({
        pagination: { pageIndex: 2, pageSize: 25 },
        sorting: [
          { id: "title", desc: false },
          { id: "priority", desc: true },
        ],
        filters: [{ id: "status", value: "open" }],
        search: "printer",
        searchBroadened: true,
      }),
    );

    expect(request).toHaveBeenCalledWith(
      {
        skip: 50,
        limit: 25,
        sort: ["title", "-priority"],
        filters: { status: "open" },
        search: "printer",
        searchBroadened: true,
      },
      undefined,
    );
    expect(result).toEqual({ rows: [TICKETS[0]], totalCount: 41 });
  });

  it("forwards the abort signal to the adapter", async () => {
    const request = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const http = new HttpDataViewRepository<Ticket>({ request, getRowId: (t) => t.id });
    const controller = new AbortController();
    await http.query(query(), controller.signal);
    expect(request.mock.calls[0]?.[1]).toBe(controller.signal);
  });

  it("advertises server-side capabilities from its options", () => {
    const http = new HttpDataViewRepository<Ticket>({
      request: vi.fn(),
      getRowId: (t) => t.id,
      search: false,
      searchScope: true,
    });
    expect(http.capabilities).toEqual({ serverSide: true, search: false, searchScope: true });
  });

  it("clamps the limit at the platform pagination cap (embedded views ask for everything)", async () => {
    // The backend refuses limit > PAGINATION_MAX_LIMIT (default 200) with a 422; an
    // embedded DataView's render-all page size must degrade, not fail.
    const request = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const http = new HttpDataViewRepository<Ticket>({ request, getRowId: (t) => t.id });
    await http.query(query({ pagination: { pageIndex: 0, pageSize: 10_000 } }));
    expect(request.mock.calls[0]?.[0].limit).toBe(200);

    // Windows stay consistent past page 0: skip is computed from the CLAMPED page
    // size, so page N is the N-th 200-row window (never skip=10000&limit=200).
    await http.query(query({ pagination: { pageIndex: 1, pageSize: 10_000 } }));
    expect(request.mock.calls[1]?.[0]).toMatchObject({ skip: 200, limit: 200 });

    const widened = new HttpDataViewRepository<Ticket>({
      request,
      getRowId: (t) => t.id,
      maxLimit: 500,
    });
    await widened.query(query({ pagination: { pageIndex: 0, pageSize: 10_000 } }));
    expect(request.mock.calls[2]?.[0].limit).toBe(500);
  });
});
