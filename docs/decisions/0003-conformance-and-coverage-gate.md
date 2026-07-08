# 0003 - Conformance and coverage gate (drift + incompleteness detection)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase A hardening (the enforced suite)
- **Supersedes/relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md),
  [ADR 0002](0002-control-plane-and-auditable-module-authority.md)

---

## Decision

Terp ships a **structured, enforced gate** that makes drift and bad usage fail
the build instead of reaching production. It has four coupled parts, each a
fail-closed control plus a build-time check:

1. **Framework-conformance scanner** (new `terp-arch` rules). Detects code that
   operates *outside* the framework / control plane:
   - `table_models_use_base_table` — every `table=True` ORM model must inherit
     `BaseTable` (no bare `SQLModel` tables that skip UUID id, timestamps, and the
     optimistic-concurrency `version`).
   - `no_app_instantiation` — app code may not construct `FastAPI()` directly;
     composition goes through `terp.core.create_app` so guards are not bypassed.
   These join the existing rules (internal/cross-module imports, policy declared,
   response models, no raw sessions, input caps, tenant scoping, and the Phase-A
   `no_adhoc_permission_literals`).

2. **Harness self-completeness meta-test**
   (`test_harness_registers_and_tests_every_rule`). The drift guard for the
   harness itself: every `check_*` scanner rule must be wired into `_ALL_RULES`
   (so `check_app` actually runs it) *and* have a matching `test_<rule>`. Adding a
   rule but forgetting to register or test it fails this meta-test — the harness
   cannot silently become incomplete.

3. **100% line-coverage gate.** The full suite enforces 100% line coverage of the
   framework (`terp.*`) via `pytest --cov=terp` with `fail_under = 100`
   (`[tool.coverage.report]`). Unexercised framework code fails the build.
   Genuinely-unreachable defensive lines opt out only with an explicit, greppable
   `# pragma: no cover`. A plain `pytest` (no `--cov`) stays fast for subset/dev
   runs; the gate run and CI add `--cov`.

4. **Authority-map visualization.** `terp inspect control-plane` renders the live
   permission model + each module's policy requirements as either text or a
   Mermaid `flowchart` (`--format mermaid`). This is the remote-audit surface from
   ADR 0002 §9.4: a reviewer reads one authority map instead of spelunking routes.

CI (`.github/workflows/ci.yml`) runs the whole gate (`uv run pytest --cov=terp`)
on every push and pull request, so enforcement does not depend on a developer
remembering to run it.

## Rationale

The platform targets non-programmers working through agents, so "remember to do
X" is not a control. Each failure mode becomes a mechanical gate:

- *Code outside the framework* (a hand-rolled model, a bare `FastAPI()`) → scanner
  rule.
- *An incomplete harness* (a rule that exists but never runs) → meta-test.
- *Untested code paths* (where drift hides) → 100% coverage.
- *Opaque authority* (hard to audit) → the generated authority map.

This is the honest boundary from ADR 0002 §9: the gate cannot prove business
*intent*, but it does prove the code stays inside the declared framework and
control plane, and that the enforcement suite itself is complete.

## Consequences

- `terp-arch` grows two scanner rules and a self-completeness meta-test; the
  example app dogfoods them clean (escape-hatch budget stays at 0).
- The framework holds **100% line coverage** (141 tests). Branch coverage is 99%
  with three known defensive partials (a non-`ModuleSpec` entry point and two
  loop-exit branches); tightening branch coverage to 100% is tracked, not blocking.
- `pytest-cov` becomes a dev dependency; `[tool.coverage]` config lives in
  `pyproject.toml`.
- New framework code must arrive with tests (or a justified `# pragma: no cover`)
  or the gate fails — coverage is now part of "done".
- A CI workflow enforces the gate independently of local habits.

## Gate command

```bash
uv run pytest --cov=terp          # full gate: tests + arch rules + 100% coverage
# local (no uv):
.venv/Scripts/python -m pytest --cov=terp
```

Status: **Accepted** — 141 tests green, 100% line coverage enforced.
