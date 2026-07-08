# ADR 0057 — files: named storage profiles + declared file references

- Status: Accepted
- Date: 2026-07-02
- Phase: Phase 2 capabilities (extends ADR 0056)
- Relates to: ADR 0056 (`terp-cap-files` — the capability this extends; its "per-file
  visibility beyond the admin+owner posture" and "S3/Azure-blob adapter" deferrals are
  addressed here), ADR 0046/0048 (the engine-adapter pattern the profile registry
  generalizes), ADR 0029 (`OwnedMixin` / object-authz — whose **narrow-only** predicate
  semantics shape the delegation design), ADR 0017 (the scope registry — same narrow-only
  property), ADR 0006 (two-layer runtime + build-time discipline)
- Adds **no** new `terp.core` surface and **no** storage-engine SDK, so the vendored core
  mirror is untouched.

## Context

Two questions landed against ADR 0056's shipped surface:

1. **Does a `file_id` column on another module's model automatically get correct
   access?** No — and implicit "can see the record ⇒ can see the file" propagation is
   exactly the object-level (BOLA) drift the platform exists to prevent. But a *bare*
   `uuid` column was also invisible: nothing declared it as a file reference, so nothing
   could enforce that access to the file follows access to the referencing record.
2. **Can any storage provider be used — and one level deeper, can different modules /
   uses ride different stores (e.g. two Azure containers)?** Any provider: yes (a
   `StorageBackend` subclass). Per-module/per-use routing: no — the seam was a single
   process-global backend, so only one store could be live at a time, and a `File` row
   did not record which store held its bytes.

A constraint that shaped both answers: the kernel's predicate seams (the scope registry,
the object-authz registry) compose with **AND** semantics — a registered predicate can
only ever *narrow* access. Delegated file access is a *widening* (a non-admin reaches a
file because their record references it), so it structurally cannot — and must not —
ride those seams.

## Decision

### 1. Named storage profiles: a keyed registry + a persisted per-row selector

The single-global seam becomes a **profile registry** (`terp.capabilities.files.storage`):

- `register_storage_backend(profile, backend)` installs a backend instance under a
  stable, code-side name at the composition root; one provider class serves many uses
  (the same Azure-style adapter registered as `"azure-invoices"` and `"azure-hr"`, one
  per container). Profile names are validated eagerly (non-empty, ≤ 64 chars) so a
  mis-wired root fails at boot, not at the first upload.
- `resolve_storage_backend(profile)` is **fail-closed**: an unknown profile raises
  `UnknownStorageProfileError` (500) — never a silent fall-through to a different,
  differently-permissioned store.
- The `"default"` profile is the shipped `LocalFilesystemStorage`; the original
  `set_storage_backend` / `active_storage_backend` / `reset_storage_backend` seam is
  preserved as sugar over it, so an app that configures nothing keeps ADR 0056's exact
  behavior.

**Routing:** `FileService.store(..., profile=...)` selects per call; a module binds its
own store per service by subclassing (`storage_profile = "azure-invoices"` — the class
default). A **client never selects a profile**: it is code-side vocabulary, and provider
credentials stay in settings / sealed config (ADR 0055), never in module code.

**Correctness:** the selected profile is **persisted** on the row (`storage_profile`,
length-capped, backfilled to `default` by migration `e3a9c47d51b8`) and `load` / `remove`
resolve the backend **the row itself names** — a later re-wiring can never read or delete
against the wrong store. The column is append-only (like `storage_key`: re-homing bytes
is an explicit migration, never a patch) and — also like `storage_key` — never leaves the
API boundary (`FileRead` omits it; the runtime test asserts the omission). `remove`
resolves the backend *before* the row delete, so a row is never destroyed while its bytes
are unreachable.

### 2. Declared file references + serve-through delegation (default-deny)

A model column that points at a `File` must be **declared**:

- `FileRef()` declares the column (a normal nullable, indexed `uuid` — no cross-package
  DB FK is imposed — whose `FieldInfo` carries a machine-readable marker;
  `is_file_reference` verifies it at runtime).
- Delegated access is **serve-through**: the referencing module loads its *own* row
  through its *own* service (that row's policy + row scope + per-row write gate already
  decided visibility), then serves the bytes with `FileService.load_for(session, row,
  column)`. `load_for` fail-closes on any column not declared with `FileRef`
  (`UndeclaredFileReferenceError`, 500) and maps an empty reference to a typed 404. The
  raw `/api/v1/files` surface stays ADMIN-only; delegation widens access to exactly one
  already-authorized row's file, never registry-wide.
- **Rejected:** delegation via a registered scope / object-authz predicate. Those seams
  are narrow-only by design (AND composition) — a predicate cannot widen access, and a
  mechanism that *could* silently widen from a registry would be the BOLA footgun this
  ADR exists to close.

**Two-layer enforcement (ADR 0006):** the runtime control is `load_for`'s fail-closed
declaration check; the build-time twin is the new `no_raw_file_references` rule — a
`table=True` model column named `file_id` / `*_file_id` not declared with `FileRef(...)`
fails the gate, so adding a file pointer *forces* the module to declare how the file is
accessed. A non-table schema (a Read DTO exposing `file_id`) is not policed.

## Consequences

- The API contract is unchanged (profiles and references are server-side), so the
  committed OpenAPI artifacts and generated TypeScript schemas need no regeneration.
- The `files` migration history gains one revision (`storage_profile`, server-default
  `default`); the conformance gate covers its upgrade → downgrade.
- `terp guide files` documents the recipes; the `no_raw_file_references` rule surfaces
  automatically in the generated `terp guide rules`.
- Deferred: shipped S3/Azure adapter packages (each is a `StorageBackend` subclass in
  its own package, per the engine-adapter budget pattern), per-tenant profile routing,
  and a maintained serve-through download route factory.
