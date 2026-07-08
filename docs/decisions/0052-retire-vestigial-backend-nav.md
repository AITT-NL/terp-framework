# 0052 - Retire the vestigial backend `ModuleSpec.nav`; navigation is frontend-authored

- **Status:** Accepted
- **Date:** 2026-07-01
- **Context phase:** Phase 4 (frontend stack), a drift-removal / code-quality pass
- **Relates:** [ADR 0041](0041-frontend-contract-openapi-export-seam.md) (the frontend
  contract seam, which explicitly left "manifest emitted from the backend vs authored in
  the frontend" as the *next* decision), [ADR 0018](0018-retire-vestigial-policy-role-projection.md)
  (precedent for retiring a vestigial kernel field with no consumers).

---

## Context

`ModuleSpec` carried a `nav: Sequence[Mapping[str, Any]]` field, and the example modules
populated it (`nav=({"label": "Notes", "to": "/notes", "icon": "note", "role": "VIEWER"},)`).
[ADR 0041](0041-frontend-contract-openapi-export-seam.md) explicitly deferred whether the
module/route/nav manifest is emitted from the backend `ModuleSpec` or authored in the
frontend.

That question has since been answered in code — in the frontend's favour. The frontend
contract (`@terp/contract`'s `manifest.ts`) states that "view names and navigation are
frontend concerns, so they are not emitted from the backend `ModuleSpec`," and
`@terp/react-core` consumes **only** the frontend `ModuleManifest.nav` (`visibleNav` →
`AppShell`).

A drift-removal audit confirmed the backend `nav` field now has **zero consumers**:

- Nothing in `create_app`, capability discovery, `terp inspect`, `terp api-docs`, or the
  exported OpenAPI reads `spec.nav`.
- It is not emitted into the contract (no `x-terp` extension), so the frontend could not
  consume it even if it wanted to.

Worse, it was actively misleading: the same navigation was declared **twice** (backend
`ModuleSpec.nav` *and* frontend `module.tsx` `nav`), and the two had already **drifted** —
the backend said `to: "/notes"` while the frontend said `to: "/"`.

## Decision

Remove `nav` from `ModuleSpec` (and its now-unused `Mapping` / `Any` imports), and drop
`nav=(...)` from the example modules. Navigation lives only in the frontend manifest.

Rationale:

- **Navigation is a UI concern.** Labels, icons, ordering, and the client-side (SPA)
  destination path are frontend decisions; the backend owns the API surface and its
  authorization policy, not the sidebar. The `role` on a nav item is only a *visibility*
  hint — actual access is already enforced by the module's `Policy`.
- **One source of truth, no drift.** With nav authored only in the frontend
  `ModuleManifest`, there is no second copy to fall out of sync (the observed `/notes` vs
  `/` drift becomes impossible by construction).
- **The API path is unaffected and is not duplication.** A view still calls
  `client.GET("/api/v1/notes/")` through the generated, typed `@terp/contract` client —
  that path is checked against the exported OpenAPI at compile time (a wrong path fails
  `tsc`), so it is a *typed reference* to the single backend source, not a hand-maintained
  copy.

If a future need arises for the backend to *drive* navigation (dynamic, permission-shaped
menus), it should be a deliberate, typed contract extension emitted into the OpenAPI and
generated for the frontend — not an untyped `Mapping` bag on `ModuleSpec`. That remains a
future decision, not today's default.

## Consequences

- A smaller, honest kernel surface: `ModuleSpec` declares only what the backend actually
  wires (`router`, `services`, `requires`, `emits` / `subscribes`, `jobs`, `policy`,
  `tenant_scoped`).
- Navigation has a single home (the frontend manifest); the backend/frontend nav
  duplication and its drift are gone.
- Purely a cleanup: the field had **no consumers**, so there is no runtime behavior change.
- Kernel edit → mirrored byte-for-byte into `vendor/terp-core` (`test_vendored_core_unmodified`).
  Gate stays green at 100% line coverage.
