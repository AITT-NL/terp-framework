# 0033 - Generic enforcement backstops in CI (ruff/bandit · pip-audit · deptry · import-linter)

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 3 finish — "ship `terp-arch`; delegate layering to a tool"
- **Supersedes/relates:** [ADR 0003](0003-conformance-and-coverage-gate.md)
  (the coverage + conformance gate), the `terp.core` layer-0 keystone
  [tests/architecture/test_core_boundary.py](../../tests/architecture/test_core_boundary.py)

---

## Decision

Phase 3 ("ship `terp-arch`; delegate layering to Tach") is completed by wiring
**generic, off-the-shelf** enforcement around the existing gate **without
weakening `terp-arch`**. The terp-specific rules keep full authority; these tools
are an independent second opinion plus the ecosystem-standard layering contract:

1. **ruff with bandit (`S`)** — a security backstop run repo-wide. `select = ["S"]`
   catches `exec`/`eval`, weak hashes, unsafe deserialization, bind-all-interfaces,
   SQL-string injection, and shell-true. The name-only heuristics (`S101` assert,
   `S105`/`S106` "looks like a password" on `SECRET_KEY` / `token_type`) are
   excused; tests excuse known-subprocess (`S603`/`S607`) + non-crypto `S311`. The
   repo is clean today with zero source edits.
2. **pip-audit** — dependency CVE scanning (advisory; the local `terp-*` editables
   are skipped as not-on-PyPI).
3. **deptry** — per-package dependency hygiene; `terp` is one PEP-420 namespace, so
   intra-namespace imports are first-party and pydantic re-exports are ignored.
4. **import-linter** — a `terp` `forbidden` contract that `terp.core` imports none
   of `terp.capabilities` / `terp.arch` / `terp.cli` / `terp.migrations`. This is a
   tool-independent mirror of the `test_core_boundary` keystone — the "delegate
   layering to a tool" item, satisfied with import-linter rather than Tach (pure
   Python, configured in `pyproject.toml`, no extra binary).

These live in a CI-only `lint` dependency group and a second CI job; they are
**not** part of the `uv run pytest --cov=terp` gate, which stays unchanged.

## Gate vs. CI-only

| Check | Where | Blocking | Layer |
|---|---|---|---|
| `pytest` + `terp-arch` + 100% coverage | gate + CI | yes | terp-specific (ADR 0003) |
| ruff bandit (`S`) | CI only | yes | generic security |
| import-linter core-layer0 | CI only | yes | generic layering (mirrors keystone) |
| pip-audit | CI only | no (advisory) | supply chain |
| deptry | CI only | no (advisory) | dependency hygiene |

The gate is reproducible offline (no network); the advisory pair needs PyPI, so
they inform rather than block. `terp-arch` remains the authoritative, fail-closed
control — import-linter only restates layer-0, never relaxes it.

## Rationale

The keystone is enforced twice (the AST test **and** import-linter) so neither is
the only control — the ADR 0006 two-layer rule, applied to layering. ruff `S`
adds a CWE-class net under terp-arch at near-zero cost; pip-audit/deptry catch
supply-chain and dependency drift the AST rules cannot see. No `terp.*` logic
changed; config-only, so the gate stays 100% green.

## Consequences

- A `lint` group adds ruff / pip-audit / deptry / import-linter (CI install).
- `pyproject.toml` gains `[tool.ruff]`, `[tool.deptry]`, `[tool.importlinter]`.
- CI gains a `generic-checks` job; the `gate` job is untouched.
- Adding a layer dependency that violates the boundary fails import-linter as well
  as the AST keystone — defense in depth.

Status: **Accepted** — gate green at 100% coverage; ruff `S` and import-linter
clean repo-wide.
