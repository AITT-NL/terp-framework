# 0034 - Agent-visibility layer: vendored read-only core mirror

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 6 (agent-visibility layer, design §10)
- **Relates:** [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md) §10
  (agent visibility without editability — this ADR ships its item 1 `vendor/terp-core/`
  + item 3 `test_vendored_core_unmodified`) and §13 Phase 6 gate; [ADR 0019](0019-agent-onboarding-and-discoverability.md)
  (the layered onboarding model — an agent in a consumer repo does not read
  `site-packages`, so core must be *present and indexed* in the workspace);
  [ADR 0030](0030-agent-surface-completeness-and-docs-parity.md) (the "docs can't lie"
  parity layer — this is the same instinct for *source* visibility); mirrors the
  byte-/import-boundary keystone in
  [`test_core_boundary.py`](../../tests/architecture/test_core_boundary.py) (ADR 0001).

---

## Context

"Packaged" must not mean "invisible." The kernel `terp.core` is a *distribution* a
consumer installs, but an agent works inside the consumer repo and does **not** read
`.venv` / `site-packages` — so a packaged-only core is dark to it. ADR 0019 makes the
*docs* reachable; this closes the §10 gap for the *source*: the agent should see the
maintained core, search it, and learn from it — **without** being able to fork it, since
the maintenance boundary (layer-0, `terp.core` imports nothing above itself) is the whole
value of a managed core.

## Decision

Vendor a **read-only, byte-exact mirror** of the packaged core under
`vendor/terp-core/src/terp/core/`, and add a build-time test that fails closed the moment
it drifts from the packaged source.

### 1. The mirror (visible, not editable)

`vendor/terp-core/` is a faithful copy of `packages/backend/core/src/terp/core` (every
`.py` + `py.typed`, `__pycache__` excluded). It is **never on the import path** — the
installed `terp-core` is what runs; the mirror exists only to be read, searched, and
indexed. A `vendor/terp-core/README.md` states it is read-only and how to refresh it. No
`terp.*` logic changed: this slice is purely additive.

### 2. The control — `test_vendored_core_unmodified`

[`test_vendored_core.py`](../../tests/architecture/test_vendored_core.py) snapshots both
trees and asserts the mirror byte-matches packaged core (no missing / extra / modified
file). Editing the mirror — or editing core and forgetting to refresh — drifts the two and
fails the gate closed. The agent reads the mirror; it cannot quietly become a second source
of truth. The refresh is one `shutil.copytree`, documented in the test and the README.

### 3. Coverage

The mirror is never imported, so it is never measured; it is also `omit`-ed
(`*/vendor/terp-core/*`) so a refresh can never perturb the 100% line-coverage gate.

### terp.arch vs runtime/boot

No `terp.arch` AST rule applies. Like the docs-parity layer (ADR 0030) this is a
visibility/completeness control, not a security one, so there is no spurious "runtime
half"; the structural guarantee is **mirror, don't fork** — the snapshot is a projection
of packaged core, so it cannot drift from what it mirrors. CODEOWNERS / `dist/`-only
publishing (§10) and frontend `workspace:*` cores remain future work; this lands the
backend mirror + its drift gate.
