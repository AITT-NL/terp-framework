# ADR 0041 — Frontend contract: the `terp openapi` export seam (Phase 4 kickoff)

- Status: Accepted
- Date: 2026-06-29
- Phase: 4 (Frontend contract + Stack A), design §7 / §13
- Relates to: ADR 0020 (`response_model` is never a table model), ADR 0030
  (generated, never hand-written, surfaces), ADR 0039 (`terp api-docs`)
- Follows: ADR 0040 (fourth adversarial-review batch) — independent, parallel work

## Context

The backend (v1) is complete and **frontend-ready**: every route declares a Read
`response_model` (ADR 0020), errors use one envelope, lists paginate, and the
example app boots cleanly — so `app.openapi()` already emits a clean OpenAPI 3.1
document (20 paths / 30 schemas, no `*Read` schema leaking a password). The four
`packages/frontend/*` packages are still stubs.

Design §7.1 makes the **API client generated from the backend OpenAPI** the first
pillar of the Frontend Contract ("one source of truth; the frontend cannot drift
from the backend"), and the §13 Phase-4 gate forbids "any stack-specific API client
or hand-rolled fetch." Before scaffolding `@terp/contract`, the contract therefore
needs a **Python-side seam that emits the OpenAPI document from the live app** — the
single artefact every stack's codegen consumes. `terp api-docs` (ADR 0039) generates
the *Python* `terp.core` surface; it does not emit the app's HTTP OpenAPI.

## Decision

Ship **`terp openapi`** as the contract's source-of-truth seam (Tier-C tooling, ADR
0006): it writes the live FastAPI app's OpenAPI document to a JSON file the frontend
codegen reads.

1. **`terp openapi --app app.main:app --out openapi.json --app-root .`** resolves a
   `module:attribute` reference to a FastAPI app — an instance *or* a zero-arg factory
   (`app.main:build`, uvicorn `--factory` style) — and writes `app.openapi()` as
   sorted, indented JSON (so a regenerated contract diffs cleanly). `--app-root` is
   placed first on `sys.path`, so the command works as an installed console script.
   A bad reference (empty module, or a target that is not an app/factory) fails closed
   with `SystemExit`.
2. **Generated, never hand-written** — the document is produced from the same object
   `create_app` returns, so the frontend client cannot drift from the backend (the
   ADR-0030 instinct applied to the HTTP contract, as `terp api-docs` does for the
   Python surface).

The remaining Phase-4 toolchain is the **direction** this unblocks, mostly fixed by
design §7 already — to be locked package-by-package as each lands, not all at once:

- `@terp/contract` — `openapi.json` → typed client (proposed: `openapi-typescript`),
  `tokens.json` via Style Dictionary, the stack-agnostic module/route/nav manifest
  types, and the `login`/`refresh`/`currentUser`/`can` auth interface.
- `@terp/react-core` (Stack A) — shell, route/nav adapter (TanStack Router), guards,
  token-only UI primitives — consuming **only** the contract.
- `@terp/eslint-boundaries` — the boundary rules as data; `@terp/conformance` — the
  shared Playwright parity suite.

Open choices recorded for confirmation (design §15 defaults apply meanwhile): JS
package manager (root already declares **npm** workspaces), the OpenAPI codegen tool,
and the bundler/unit-runner (proposed: Vite + Vitest).

## Consequences

- Phase 4 has a concrete, tested starting point: a consumer runs `terp openapi` and
  feeds the result to codegen; no hand-rolled client is ever needed (the §13 gate).
- Whether the module/route/nav manifest is **emitted from the backend** (`ModuleSpec`
  already carries a `nav` field) or authored in the frontend is the next decision,
  taken with the `@terp/contract` scaffolding — not pre-judged here.
- The command is generic (any `module:attribute`), so it serves the example app and
  any consumer app identically.

## Enforcement

- `test_cli_openapi` exercises the live example app: the spec is written and well-formed,
  a factory reference resolves, a non-app / bad reference fails closed, and — locking the
  ADR-0020 property at the contract boundary — **no `*Read` schema serializes a password**.
- Runtime + test only; there is no module-authored pattern to police, so no `terp.arch`
  AST rule applies (the honest two-layer shape per ADR 0006). The gate stays 100% line
  coverage.
