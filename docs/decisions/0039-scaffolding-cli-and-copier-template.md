# ADR 0039 — Scaffolding: `terp new module`, the copier template, and `terp api-docs` (Phase 5)

- Status: Accepted
- Date: 2026-06-29
- Phase: 5 (Scaffolding — copier template + `terp` CLI), design §13
- Supersedes / relates to: ADR 0019 (agent onboarding), ADR 0006 (Tier-C sugar),
  ADR 0030 (generated, parity-tested surfaces), ADR 0023 (`build_crud_router`)

## Context

Phases 1–7 shipped the kernel, the capability profile, the harness, packaged
migrations, and the agent-onboarding surfaces (`terp guide`, generated rules,
vendored core). The remaining onboarding gap was **authoring ergonomics**:
`template/` and `terp-cli` were skeletons, so a new client repo and a new module
were hand-built. Design §13 Phase 5 gate: *`terp new module billing` creates a
module that passes the local gate without manual central registration.*

## Decision

Ship the Tier-C scaffolding layer — readable code you own, never a runtime black
box (ADR 0006 / IMPLEMENTATION_PLAN §10):

1. **`terp new module <name>`** emits the canonical five slots
   (`models`/`schemas`/`service`/`router`/`module` + `__init__`) into
   `<package>/modules/<name>/`. The output passes **every** `terp.arch` rule out of
   the box; the only step before green is the first migration (`terp migrate make`),
   exactly as the `tables_have_migrations` rule directs. A bad name or an existing
   destination fails closed (no partial overwrite).
2. **Copier template** (`template/project/`, `_subdirectory: project`) scaffolds a
   runnable repo: `create_app` + a base-profile control plane + the discovered
   capability stack (auth · identity · users · access · audit) + one example module +
   CI/`AGENTS.md`/an architecture test. The meta `README.md`/`AGENTS.md` stay out of
   the rendered repo.
3. **`terp api-docs`** generates `platform-api.md` + `terp_core.pyi` from the **live**
   `terp.core` surface — generated, never hand-written, so it cannot drift (the ADR
   0030 instinct applied to the API contract). It completes the Phase-1 deferred
   `.pyi` item.
4. **`terp check`** runs `assert_app_clean` locally (== CI).

The CLI stays un-pip-installed in the dev venv; tests inject `cli/src` on `sys.path`,
matching `test_cli_inspect` / `test_cli_guide`. Scaffolding logic is 100%-covered
under the `--cov=terp` gate; the template/copier sources are consumer artefacts (not
`terp.*`), validated by structural integrity tests.

## Consequences

- A 10-minute module is real: `terp new module` → fill fields → `terp migrate make` →
  green. The generated module registers by a one-line spec import in `main.py`;
  installed capabilities self-register via discovery (no composition-root edit).
- Scaffolding is sugar, not a path: a hand-written module is held to the identical
  rules, so the gate — not the generator — remains the source of truth.
- `.pyi`/api-docs are generated from the kernel, so they age with it.

## Enforcement

- `terp new module` shape: `test_cli_scaffold` asserts the scaffold passes every rule
  but `tables_have_migrations`; api-docs/check covered there. Template integrity:
  `test_template`. Gate stays 100% line coverage.
