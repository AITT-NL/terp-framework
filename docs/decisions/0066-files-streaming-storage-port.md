# ADR 0066 — files: streamed, file-like storage port (`put` / `open`, no whole-file buffering)

- Status: Accepted
- Date: 2026-07-04
- Phase: Phase 2 capabilities (refines ADR 0056 / 0057)
- Relates to: ADR 0056 (`terp-cap-files` — the capability this refines; its deferred
  "streaming upload/download path" is delivered here), ADR 0057 (named storage profiles +
  declared references — the profile registry and the `storage_key` / `storage_profile`
  posture are unchanged and compose with the new port), ADR 0046/0048 (the engine-adapter
  pattern the port follows — a tiny port + a shipped reference adapter + one-line swapping),
  ADR 0006 (two-layer runtime + build-time discipline)
- Adds **no** new `terp.core` surface and **no** storage-engine SDK: the port lives in the
  capability, so the vendored core mirror is untouched.

## Context

ADR 0056 shipped the `StorageBackend` port as `put(key, data: bytes)` / `get(key) -> bytes`
and explicitly deferred "a streaming upload/download path (today's surface buffers within
the 25 MiB cap)". That byte-oriented contract *structurally* forces the whole file into
memory on both paths — upload (`read` → `hashlib.sha256(data)` → `put(key, data)`) and
download (`get(key)` → `Response(content=all_bytes)`) — so:

- the practical file ceiling is RAM-per-request, not disk / object-store capacity;
- a future cloud adapter (S3 / Azure Blob, each deferred to its own ADR) could not use the
  SDK-native streamed transfer (`boto3.upload_fileobj` / Azure `upload_blob`) without
  re-buffering the whole blob;
- the upload route carried a bespoke pre-parse whole-body buffer
  (`_SizeCappedUploadRoute` + `_capped_request_body`) to cap size *before* the multipart
  parse — itself a full in-memory copy of the request body.

## Decision

### 1. The port becomes file-like and streamed

`StorageBackend` is now:

- `put(key, source: BinaryIO)` — copies the readable binary *source* under *key* by reading
  it in chunks (never materializing the whole blob). The `LocalFilesystemStorage` reference
  adapter uses `shutil.copyfileobj` into `path.open("wb")`; a cloud adapter maps straight
  onto `boto3.upload_fileobj` / Azure `upload_blob`.
- `open(key) -> BinaryIO` — returns a readable binary stream positioned at the blob start
  (or raises `FileNotFoundError`, mapped to a typed 404); the caller closes it. The local
  adapter returns `path.open("rb")`; a cloud adapter returns the SDK's streaming body.
- `delete(key)` — unchanged (idempotent).

The local adapter's fail-closed root-containment check (`_path_for`) is unchanged, so the
traversal guard still fires before any I/O. A second, non-filesystem **in-memory** backend
in the test suite proves the file-like port swaps without touching the service — the
`StorageBackend` swap criterion, now on the streamed contract.

### 2. The service streams, hashes, and size-caps in flight

`FileService.store(..., source: BinaryIO, max_bytes: int | None = None)` wraps *source* in a
`_DigestingReader` that folds each chunk into a running SHA-256 + byte count and raises a
typed `ValidationFailedError` the instant the total crosses `max_bytes` — so the size cap is
enforced **mid-stream**, never by buffering the whole upload, and the recorded digest / size
describe exactly the stored bytes. The blob `put` runs **inside** the compensation guard, so
an over-cap upload (or a failed row write) deletes the partial blob before the error
propagates — the "a committed row always has its bytes; a failed upload leaves nothing
behind" invariant is preserved. `FileService.open_stream(id) -> (File, BinaryIO)` is the new
scope-honoring streamed read; `load` remains a buffered convenience over it for the
serve-through delegation read (`load_for`).

### 3. The routes stream both directions

- **Download** returns a `StreamingResponse` that pulls the backend stream in fixed-size
  chunks and closes it in a `finally` (bounded memory per read, handle released even on a
  mid-stream client disconnect). The sanitized RFC 5987 `Content-Disposition` is unchanged.
- **Upload** is a *sync* handler (FastAPI runs it in the threadpool, so the blocking copy
  never stalls the event loop) that streams the parsed part's spooled file straight into the
  service under the `MAX_UPLOAD_BYTES` cap. The bespoke pre-parse whole-body buffer
  (`_SizeCappedUploadRoute` / `_capped_request_body`) is **removed**: the kernel's
  `RequestSizeLimitMiddleware` still bounds the raw request body up front (the socket-level
  DoS guard, counting bytes on the fly), and the service's streamed cap is the precise
  per-resource control that compensates the partial blob on overrun.

### 4. Two-layer enforcement (ADR 0006)

The streamed size cap is the fail-closed **runtime** control (mid-stream refusal + blob
compensation); the storage-key-never-serialized posture and the traversal-containment check
keep their existing runtime + build-time pairs, and the capability still runs through the
arch harness. No new AST rule is needed — the port-shape change introduces no new
module-authored pattern to police (the runtime-only precedent of ADR 0031 / 0036).

## Consequences

- The API contract (OpenAPI) is **unchanged**: upload still returns `FileRead` (201), and
  download is still a binary response with no `response_model` — so the committed OpenAPI
  artifacts and generated TypeScript schemas need no regeneration.
- **No schema change ⇒ no new migration**; the `file_object` columns (including
  `size` / `sha256`) are unchanged, now computed from the streamed bytes.
- The capability's escape-hatch budget is unchanged
  (`arch-allow-routes-declare-response-model`: 1 — the binary download route).
- The `StorageBackend` **public contract changed** (`get` → `open`, `bytes` → file-like), a
  breaking change to the ADR-0056/0057 port: an out-of-tree adapter updates two method
  signatures. In-tree, the local adapter, `FileService`, the router, and both the arch and
  example test suites are migrated; the vendored core mirror is untouched (the port lives in
  the capability, never in `terp.core`).
- **Known follow-up (not addressed here):** the effective default upload ceiling is
  `min(MAX_UPLOAD_BYTES, security.max_request_bytes)` — the core request-size middleware
  defaults to 1 MiB, so out of the box an upload is capped at 1 MiB, not 25 MiB, and raising
  the files ceiling today means raising the *global* request cap. Reconciling this (a
  settings-driven, per-route allowance) is a separate change. *(Closed by ADR 0067.)*
- **Deliberate trade-off in removing the pre-parse cap:** with the default config the new
  posture is *stricter* (the kernel middleware refuses at 1 MiB at the socket, versus the old
  route buffering up to 25 MiB of body in RAM before refusing). But in a deployment that
  **raises** `security.max_request_bytes` above `MAX_UPLOAD_BYTES`, the multipart parser now
  spools an over-25-MiB body to a bounded temp file before the mid-stream cap refuses and
  compensates — where the old pre-parse guard refused at 25 MiB during the body read. Disk
  spool bounded by the global cap on an ADMIN-only route is an accepted cost of deleting the
  bespoke whole-body RAM buffer; the per-route reconciliation above closes it properly.
- Deferred (unchanged from ADR 0056 / 0057, now clean drop-ins over the file-like port):
  shipped S3 / Azure adapter packages, presigned-URL offload (bytes never transit the app),
  resumable / chunked uploads, content-addressed dedup, and per-file visibility beyond the
  admin + owner posture.
