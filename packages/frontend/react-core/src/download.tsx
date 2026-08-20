/**
 * Handing bytes to the browser as a named download (ADR 0096).
 *
 * `useFileDownload` covers the stored-file case: a `FileMeta` id, fetched from the files
 * capability's content endpoint. What it does not cover is the other half of the same
 * need — **an artifact the backend generates on demand** ("download this revision as
 * proof", a CSV export, a signed evidence bundle). Those have no stored file id, and the
 * only ways to reach them were a raw `fetch` (refused: one typed egress path) or a raw
 * `<a href>` (which carries no bearer token, so it 401s or, worse, silently downloads an
 * error page). The observed outcome was the feature being dropped rather than built.
 *
 * So the blob-to-anchor dance lives here once, and `useEndpointDownload` reaches any
 * authorized GET through the session client. `path` is a plain string, deliberately and
 * unusually: the generated client is keyed by the app's own schema, which this package
 * cannot see, and a byte-stream route is app-specific by nature. Everything else that
 * matters — the base URL, the bearer token, cookie credentials, the refusal on a non-2xx —
 * still comes from the client, which is what the raw alternatives threw away.
 */

import { useCallback } from "react";

import { useTerpClient } from "./TerpProvider";
import type { TerpClient } from "@terpjs/contract";

/** What to download: where the bytes come from, and what the file should be called. */
export interface DownloadTarget {
  /** API path, e.g. `/api/v1/revisions/{id}/evidence` with `params` filling `{id}`. */
  path: string;
  /** Filename offered to the browser (extension included). */
  filename: string;
  /** Path placeholders to substitute, e.g. `{ id: revision.id }`. */
  params?: Record<string, string>;
  /** Query string to append; `undefined` values are omitted. */
  query?: Record<string, string | undefined>;
}

/**
 * Save *blob* as a named download.
 *
 * Exported because it is the one piece a screen cannot avoid re-implementing when it
 * already holds the bytes (a client-side CSV, a canvas export) — and every hand-rolled
 * copy leaks the object URL, which is why the revoke is in a `finally` here.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Fill `{placeholder}` segments and append the query string, dropping unset values. */
export function downloadUrl(target: DownloadTarget): string {
  let path = target.path;
  for (const [name, value] of Object.entries(target.params ?? {})) {
    path = path.replaceAll(`{${name}}`, encodeURIComponent(value));
  }
  const unfilled = /\{([A-Za-z_][A-Za-z0-9_]*)\}/.exec(path);
  if (unfilled !== null) {
    // Fail closed rather than requesting a literal `{id}`: the server would 404 or, on a
    // permissive route, hand back somebody else's bytes.
    throw new Error(
      `Download path "${target.path}" still contains the placeholder "${unfilled[0]}" — ` +
        `pass it in \`params\` (e.g. params: { ${unfilled[1]}: row.id }).`,
    );
  }
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(target.query ?? {})) {
    if (value !== undefined) {
      query.append(name, value);
    }
  }
  const suffix = query.toString();
  return suffix.length > 0 ? `${path}?${suffix}` : path;
}

/**
 * Download a generated artifact from an authorized endpoint (ADR 0096).
 *
 * ```tsx
 * const download = useEndpointDownload();
 * void download({
 *   path: "/api/v1/revisions/{revisionId}/evidence",
 *   params: { revisionId: revision.id },
 *   filename: `revision-${revision.number}.json`,
 * });
 * ```
 *
 * Rejects on a non-2xx response, so a caller can surface the failure — a raw anchor would
 * have saved the error body under the intended filename instead.
 */
export function useEndpointDownload(): (target: DownloadTarget) => Promise<void> {
  const client = useTerpClient();
  return useCallback(
    async (target: DownloadTarget) => {
      const blob = await fetchDownload(client as unknown as TerpClient, target);
      saveBlob(blob, target.filename);
    },
    [client],
  );
}

/**
 * Fetch a download target's bytes through the session client.
 *
 * Separate from the hook so a caller that wants the blob for something *other* than
 * saving it (a preview, a checksum) does not have to save it first.
 */
export async function fetchDownload(client: TerpClient, target: DownloadTarget): Promise<Blob> {
  const url = downloadUrl(target);
  const { data, error, response } = await (
    client as unknown as {
      GET: (
        path: string,
        init: { parseAs: "blob" },
      ) => Promise<{ data?: unknown; error?: unknown; response: Response }>;
    }
  ).GET(url, { parseAs: "blob" });
  if (error !== undefined || !response.ok) {
    throw new Error(
      `Download of ${url} failed with HTTP ${response.status}. The endpoint must be a GET ` +
        "the current session is authorized for.",
    );
  }
  return data as Blob;
}
