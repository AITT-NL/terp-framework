# 0042 - Close two adversarial-review open questions: module-shape completeness + api-docs drift gate

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 3 (harness) + Phase 5 (scaffolding) follow-up to the fourth
  adversarial-review batch
- **Relates:** [ADR 0040](0040-adversarial-review-fourth-batch.md) (the batch whose two
  remaining open questions this closes), [ADR 0037](0037-finish-universal-rule-set.md)
  (`canonical_module_shape`, strengthened here), [ADR 0030](0030-agent-surface-completeness-and-docs-parity.md)
  (generated, drift-guarded surfaces), [ADR 0039](0039-scaffolding-cli-and-copier-template.md)
  (the copier template + `terp api-docs` this wires a drift gate around).

> ADR number 0041 was taken by a parallel frontend-contract OpenAPI export decision; this
> follow-up is 0042.

---

## Context

The fourth adversarial review (ADR 0040) fixed five findings and left four open questions.
Two were small, concrete robustness gaps worth closing now:

- **Module-shape completeness.** `canonical_module_shape` only fired for a directory that
  already declared a `module.py` manifest. A `modules/<name>/` dir with `service.py` /
  `router.py` but **no** `module.py` was invisible to it **and** to
  `modules_declare_policy` (which only scans `module.py` files) — so a half-built module
  could ship a router with no declared `Policy`, unnoticed by the gate.
- **api-docs drift.** `terp api-docs` generates `docs/platform-api.md` + `terp_core.pyi`
  from the live kernel, but nothing regenerated-and-verified them, so a consumer that
  commits the contract and later upgrades Terp could let it silently fall behind.

## Decision

### 1. `canonical_module_shape` enforces the full shape on every wired module

`module.py` joins the required canonical slot set, and a directory under `modules/` is
treated as a module once it ships a manifest (`module.py`) **or** a mounted `router.py` —
the two "this is a real, wired module" signals. It must then carry **all** five slots, so
a dir that mounts a `router.py` with **no** `module.py` is now flagged for the missing
manifest instead of being skipped. A directory with neither signal (a partial, or a
shared-asset / helper dir) is left alone, so the rule does not over-reach. This stays
build-time governance (the honest shape per ADR 0006, like the prior version of this
rule); it has no separate runtime half.

### 2. The copier template CI regenerates the API contract and fails on drift

The generated repo's CI now runs `terp api-docs --out docs` and `git diff --exit-code --
docs` after the gate, so a committed `docs/platform-api.md` / `terp_core.pyi` that drifts
from the installed kernel fails CI. It is a no-op until a consumer commits `docs/`, so a
fresh scaffold stays green; once the contract is committed, an upgrade that forgets to
regenerate is caught. `test_template` asserts the CI ships the drift step.

## Consequences

- A module directory can no longer ship without its manifest (and therefore without a
  declared `Policy`) unnoticed; the example app, the `terp new module` scaffold, and the
  copier template module all carry the full five-slot shape, so the gate stays green and
  the example budget stays `{}`.
- A consumer's generated API reference cannot silently rot; the drift gate is the same
  "generate, then verify" instinct as the vendored-core mirror (ADR 0034) and the docs
  parity tests (ADR 0030), applied to the consumer contract.
- Remaining ADR-0040 open questions (the durable event outbox / `_after_write` external-I/O
  dual-write, and a second divergent tenancy consumer) stay on the roadmap — they are
  subsystem-sized, not robustness tweaks.

## Enforcement

- Module shape: the rewritten `test_canonical_module_shape` covers a manifest-less module
  dir (flagged for `module.py`), a pure-helper dir (left alone), and a complete five-slot
  dir (clean). api-docs drift: `test_template` asserts the CI runs `terp api-docs` +
  `git diff --exit-code`. Gate stays 100% line coverage.
