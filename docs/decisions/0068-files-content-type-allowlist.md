# ADR 0068 — files: deployment-configurable upload content-type allowlist

- Status: Accepted
- Date: 2026-07-04
- Phase: Phase 2 hardening (extends ADR 0056/0066/0067)
- Relates to: ADR 0056 (the files capability; shipped with content type as descriptive,
  length-capped metadata and no allowlist), ADR 0067 (the sibling deployment knob —
  `configure_upload_limit` — whose composition-root seam shape this reuses), ADR 0057
  (the storage-profile registry that set the seam pattern), ADR 0006 (two-layer
  discipline), ADR 0011 (central configuration is a *how* knob at the composition root)
- Adds **no** new `terp.core` surface — the vendored core mirror is untouched.

## Context

The files capability accepted **any** upload content type: `content_type` was validated
only for length and stored as descriptive metadata. That is a defensible default — the
platform cannot know which types an application considers safe — but it left a common
hardening requirement ("images only", "no executables") impossible without forking the
capability. OWASP file-upload guidance lists content-type restriction among the baseline
controls; the original capability task specified it, and it was never built.

## Decision

### One composition-root line, enforced in the service chokepoint

- `configure_allowed_content_types(["application/pdf", "image/*"])` /
  `active_allowed_content_types()` / `reset_allowed_content_types()` — the same
  module-level, composition-root seam shape as the storage registry (ADR 0057) and the
  upload limit (ADR 0067). Entries are exact media types or whole-subtype wildcards
  (`image/*`), normalized (lowercased, parameters stripped) and validated **eagerly**: an
  empty list or a shapeless entry (`"pdf"`, `"*/pdf"`, `"application/"`) raises
  `ValueError` at boot, not at the first upload.
- The check runs at the **top of `FileService.store`** — the chokepoint every upload path
  crosses — so neither the router nor a programmatic caller can bypass it, and a
  disallowed type refuses **before any byte lands** (no blob, no compensation needed).
  Matching normalizes the incoming type the same way (`Application/PDF; charset=binary` →
  `application/pdf`) and a wildcard never leaks past its type segment (`image/*` does not
  admit `imagex/png`).
- A refusal is a typed **415** (`UnsupportedContentTypeError`, code
  `content_type_not_allowed`) in the uniform error envelope.

### The default stays allow-everything, explicitly

`None` (unconfigured) allows every type — ADR 0056's shipped posture, unchanged for
existing deployments. Allow-everything is expressed by *not configuring* the allowlist,
never by a `*/*` entry: a wildcard that reads like a restriction would be a lie in the
composition root. The client-declared content type remains advisory metadata —
content *sniffing* (magic-byte verification) is out of scope and recorded as deferred.

## Two-layer enforcement (ADR 0006)

Runtime: the fail-closed chokepoint check + eager configuration validation. Build-time:
seam tests (default posture, exact/wildcard/normalization matches, lookalike-wildcard
refusal, nothing-stored-on-refusal, shapeless-config refusals) and an example-app
end-to-end test (415 envelope through `/api/v1/files`, allowlisted type still
round-trips). No new AST rule — a deployment knob with a safe default introduces no
module-authored pattern to police (the ADR 0036 runtime-only precedent).

## Consequences

- The OpenAPI contract is unchanged (the allowlist is a runtime refusal, not a schema
  change); no migration (no model change); the capability's escape-hatch budget is
  unchanged.
- `terp guide files` documents the recipe alongside the upload-limit retune.
- Deferred: content sniffing / magic-byte verification of the declared type, per-profile
  or per-collection allowlists, and surfacing the configured allowlist in `terp inspect`.
