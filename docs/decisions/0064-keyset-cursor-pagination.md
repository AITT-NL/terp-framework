# 0064 - Keyset (cursor) pagination with an opt-in total

- **Status:** Accepted
- **Date:** 2026-07-04
- **Context phase:** Production-readiness gaps (the 2026-06-24 direction &
  completeness review, item **M5**)
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (pagination as a Tier-A mandatory control), [ADR 0024](0024-health-endpoints-and-pool-config.md)
  (the same review's pool-tuning item), [ADR 0065](0065-sync-data-layer-decision.md)
  (the review's other data-layer decision)

---

## Context

Every Terp list endpoint is required to paginate (the `list_routes_paginate` rule +
the capped `Page[T]` envelope), but the only shipped shape was **offset** pagination:
`BaseService._paginate` runs an exact `COUNT(*)` on *every* page **and** an
`OFFSET N` scan whose cost grows linearly with the page's depth. The
direction & completeness review flagged this (M5, "High at scale"): on a large table
the mandatory `COUNT(*)` dominates the query cost and deep pages degrade, so the
mandatory-pagination control becomes a performance tax exactly where it matters
most.

## Decision

**Offer keyset (cursor) pagination as a first-class, opt-in alternative — same
non-droppable row scope, no `OFFSET`, and the total only on request.**

1. **`CursorPage[T]` + `CursorPaginationDep`** (`terp.core.pagination`): a route takes
   `cursor` (opaque, `None` for the first page), `limit` (same hard caps as
   `PaginationDep`), and `include_total` (default **false** — the `COUNT(*)` is now
   opt-in, review M5's "opt-out of the total" inverted to secure-by-default-cheap).
   The envelope is `{items, next_cursor, limit, total}`; `next_cursor` is `None` on
   the last page and `total` is `None` unless asked.
2. **`BaseService.list_by_cursor(session, pagination=...)`** walks the stable
   `(created_at, id)` keyset: each page selects rows strictly *after* the cursor's
   position (`created_at > x OR (created_at = x AND id > y)`), ordered by
   `(created_at, id)` with `id` as the tie-break, fetching `limit + 1` rows to derive
   `next_cursor` without a count. It builds on the same **non-droppable
   `base_query()`** as every other read, so soft-delete / tenant / registered row
   predicates apply identically to both pagination styles.
3. **The cursor is opaque and fail-closed:** URL-safe base64 of the row's
   `created_at` + `id` (both values the client already received on the row — no
   secret, no state). `decode_cursor` maps any tampered / garbled value to the typed
   `ValidationFailedError` (uniform 400 envelope), never a leaked 500.
4. **Offset `Page[T]` stays the default** and the contract for every existing
   endpoint (`build_crud_router`, the base profile, `@terp/contract`) is unchanged —
   this is purely additive, per the Tier-C "sugar never the only path" posture. The
   `list_routes_paginate` rule already accepts any non-bare-collection
   `response_model`, so a `CursorPage[T]` route passes without a rule change.

## Consequences

- A large-table list endpoint can drop both scale costs (the per-page `COUNT(*)` and
  the deep-`OFFSET` scan) by switching its dependency and envelope — the service call
  changes from `list` to `list_by_cursor`; row scope, audit, and caps are identical.
- `created_at` ordering means a cursor walk is insert-ordered; a differently-sorted
  keyset (e.g. by a business column) remains a bespoke service method building on
  `base_query()` — deliberately not generalized until a consumer proves the need.
- Two envelopes now exist; the guide's service recipe teaches when to prefer which
  (offset for small/admin tables where a total matters; keyset for feeds and large
  tables).
- No new arch rule: pagination remains enforced by `list_routes_paginate`; which of
  the two capped envelopes a route uses is a performance choice, not a security
  boundary (ADR 0006 — no spurious rule).
