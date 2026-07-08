// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  InMemoryViewStateRepository,
  LocalStorageViewStateRepository,
} from "./viewState";
import { emptyDataViewState } from "../types";
import type { DataViewState } from "../types";

function sampleState(): DataViewState {
  return {
    columnVisibility: { status: false },
    columnOrder: ["title", "status"],
    columnSizing: { title: 240 },
    sorting: [{ id: "title", desc: true }],
    filters: [{ id: "status", value: "open" }],
    search: "printer",
  };
}

describe("LocalStorageViewStateRepository", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it("round-trips a state per viewId", () => {
    const repo = new LocalStorageViewStateRepository();
    repo.save("tickets.list", sampleState());
    expect(repo.load("tickets.list")).toEqual(sampleState());
  });

  it("isolates views from each other", () => {
    const repo = new LocalStorageViewStateRepository();
    repo.save("a", sampleState());
    repo.save("b", { ...emptyDataViewState(), search: "other" });
    expect(repo.load("a")?.search).toBe("printer");
    expect(repo.load("b")?.search).toBe("other");
  });

  it("returns undefined when nothing was persisted", () => {
    expect(new LocalStorageViewStateRepository().load("missing")).toBeUndefined();
  });

  it("falls back to defaults on corrupt JSON", () => {
    window.localStorage.setItem("terp.dataview.bad", "{not json");
    expect(new LocalStorageViewStateRepository().load("bad")).toBeUndefined();
  });

  it("falls back to defaults on a wrong envelope version", () => {
    window.localStorage.setItem(
      "terp.dataview.old",
      JSON.stringify({ version: 999, state: sampleState() }),
    );
    expect(new LocalStorageViewStateRepository().load("old")).toBeUndefined();
  });

  it("falls back to defaults on schema-invalid state shapes", () => {
    window.localStorage.setItem(
      "terp.dataview.shape",
      JSON.stringify({
        version: 1,
        state: { ...sampleState(), columnSizing: { title: "wide" } },
      }),
    );
    expect(new LocalStorageViewStateRepository().load("shape")).toBeUndefined();
  });

  it("supports a custom key prefix", () => {
    const repo = new LocalStorageViewStateRepository("myapp.views");
    repo.save("v", sampleState());
    expect(window.localStorage.getItem("myapp.views.v")).not.toBeNull();
  });
});

describe("InMemoryViewStateRepository", () => {
  it("round-trips per viewId and isolates views", () => {
    const repo = new InMemoryViewStateRepository();
    repo.save("a", sampleState());
    expect(repo.load("a")).toEqual(sampleState());
    expect(repo.load("b")).toBeUndefined();
  });

  it("returns copies so stored state cannot be mutated in place", () => {
    const repo = new InMemoryViewStateRepository();
    repo.save("a", sampleState());
    const loaded = repo.load("a");
    loaded!.columnSizing.title = 1;
    expect(repo.load("a")?.columnSizing.title).toBe(240);
  });
});
