import type { DataViewState, ViewStateRepository } from "../types";
import { emptyDataViewState } from "../types";

/** Version of the persisted envelope; bump when {@link DataViewState}'s shape changes. */
const ENVELOPE_VERSION = 1;

interface Envelope {
  version: number;
  state: DataViewState;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

function isSorting(value: unknown): value is { id: string; desc: boolean }[] {
  return (
    Array.isArray(value) &&
    value.every(
      (entry) =>
        isRecord(entry) && typeof entry.id === "string" && typeof entry.desc === "boolean",
    )
  );
}

function isFilters(value: unknown): value is { id: string; value: unknown }[] {
  return (
    Array.isArray(value) &&
    value.every((entry) => isRecord(entry) && typeof entry.id === "string" && "value" in entry)
  );
}

function isRecordOf(value: unknown, kind: "boolean" | "number"): boolean {
  return isRecord(value) && Object.values(value).every((entry) => typeof entry === kind);
}

/** Validate a parsed envelope; anything malformed falls back to `undefined` (defaults). */
function parseEnvelope(raw: string): DataViewState | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return undefined;
  }
  if (!isRecord(parsed) || parsed.version !== ENVELOPE_VERSION || !isRecord(parsed.state)) {
    return undefined;
  }
  const state = parsed.state;
  if (
    !isRecordOf(state.columnVisibility, "boolean") ||
    !isStringArray(state.columnOrder) ||
    !isRecordOf(state.columnSizing, "number") ||
    !isSorting(state.sorting) ||
    !isFilters(state.filters) ||
    typeof state.search !== "string"
  ) {
    return undefined;
  }
  return {
    columnVisibility: state.columnVisibility as Record<string, boolean>,
    columnOrder: state.columnOrder,
    columnSizing: state.columnSizing as Record<string, number>,
    sorting: state.sorting,
    filters: state.filters,
    search: state.search,
  };
}

/**
 * {@link ViewStateRepository} over `localStorage`, storing a schema-validated, versioned
 * envelope per `viewId`. Corrupt or outdated data (bad JSON, wrong version, wrong shapes)
 * is treated as "nothing persisted" so the view falls back to its defaults; storage
 * failures (quota, privacy mode) are swallowed — preferences are best-effort.
 */
export class LocalStorageViewStateRepository implements ViewStateRepository {
  private readonly prefix: string;

  constructor(prefix = "terp.dataview") {
    this.prefix = prefix;
  }

  private key(viewId: string): string {
    return `${this.prefix}.${viewId}`;
  }

  load(viewId: string): DataViewState | undefined {
    let raw: string | null;
    try {
      raw = window.localStorage.getItem(this.key(viewId));
    } catch {
      return undefined;
    }
    return raw === null ? undefined : parseEnvelope(raw);
  }

  save(viewId: string, state: DataViewState): void {
    const envelope: Envelope = { version: ENVELOPE_VERSION, state };
    try {
      window.localStorage.setItem(this.key(viewId), JSON.stringify(envelope));
    } catch {
      // Best-effort persistence: never let a full/blocked storage break the view.
    }
  }
}

/**
 * {@link ViewStateRepository} in memory — for tests and for views without a `viewId`
 * (preferences last for the component's lifetime only).
 */
export class InMemoryViewStateRepository implements ViewStateRepository {
  private readonly store = new Map<string, DataViewState>();

  load(viewId: string): DataViewState | undefined {
    const state = this.store.get(viewId);
    // Return a copy so callers can't mutate the stored state in place.
    return state === undefined ? undefined : structuredClone(state);
  }

  save(viewId: string, state: DataViewState): void {
    this.store.set(viewId, structuredClone(state));
  }
}

export { emptyDataViewState };
