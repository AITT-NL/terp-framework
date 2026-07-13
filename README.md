# Terp — Trusted Enterprise Reinforced Platform

> **Build on high ground.**

Terp is a secure‑by‑default, agent‑friendly application platform. It pairs a
maintained **core** with opt‑in **capabilities** and client‑written **modules**,
so teams — and their coding agents — ship business features fast without drifting
off the safe path.

## Why Terp

- **Secure by default, opt‑out by exception.** Every security control ships with a
  safe default and a visible, budgeted escape hatch. Forgetting a control fails
  *closed* (denied / won't boot), never open.
- **Two‑layer enforcement.** Every invariant is both a fail‑closed **runtime
  control** and a build‑time **fitness test** (`terp.arch`). The test catches the
  omission; the runtime control is what actually protects production.
- **A small, curated surface.** Modules import only `terp.core`'s published API
  plus the capabilities they declare — never internals, never siblings.
- **Agent‑first ergonomics.** Convention over configuration, precise and fixable
  rule messages, and an in‑repo `terp` CLI that explains the platform.

## Architecture

| Layer | What it is |
|---|---|
| **Core** (`terp.core`) | The maintained kernel: base classes (`BaseTable`, `BaseSchema`, `BaseService`), the `ModuleSpec` / `Policy` authority seam, the uniform error envelope, pagination, secure config, and the `create_app` composition root. |
| **Capabilities** (`terp.capabilities.*`) | Opt‑in, self‑registering features: `auth`, `identity`, `users`, `groups`, `access` (RBAC), `tenancy`, `audit`, `eventbus`, `files`, `webhooks`, `oidc`, `outbox`, `sync`, `redis` (shared stores), `jobs_celery`, `scheduler_apscheduler`, `scheduler_celery_beat`. |
| **Modules** | The client's business code — the *only* editable surface. |
| **Harness** (`terp.arch`) | The build‑time fitness suite, shipped as a dependency so clients run it but cannot weaken it. |
| **CLI** (`terp`) | `terp inspect` (authority maps) and `terp guide` (in‑repo platform docs). |

## Monorepo map

```text
packages/backend/core           terp-core    → import terp.core            (kernel)
packages/backend/arch           terp-arch    → import terp.arch            (fitness harness)
packages/backend/cli            terp-cli     → `terp` command
packages/backend/migrations     terp-migrations → import terp.migrations   (migration engine)
packages/backend/capabilities   terp-cap-*   → import terp.capabilities.*  (opt-in)
packages/frontend/contract      @terp/contract        (client + tokens + manifest types)
packages/frontend/react-core    @terp/react-core      (first stack: React)
packages/frontend/eslint-boundaries  @terp/eslint-boundaries
packages/frontend/conformance   @terp/conformance     (Playwright parity suite)
apps/example                    neutral example app consuming the packaged core
template/                       copier skeleton (CI, AGENTS.md)
vendor/terp-core                byte-for-byte mirror of packages/backend/core

```

## Quickstart

```bash
uv run pytest                      # syncs the workspace and runs the full gate
```

Without `uv`, use a venv with the kernel installed editable:

```bash
python -m venv .venv
.venv/bin/python -m pip install pytest -e packages/backend/core   # Windows: .venv/Scripts/python
.venv/bin/python -m pytest
```

`apps/example/` is the dogfood: a neutral secure‑CRUD app (`notes`, `tasks`,
`journals`, and `projects` modules) that exercises every framework guarantee
end‑to‑end and passes the architecture harness clean.

## Non‑negotiable defaults

1. Python namespace **`terp.*`** (never `platform.*`). npm **`@terp/*`**. CLI **`terp`**.
2. A single platform **monorepo** (separate packages, not separate repos).
3. First frontend stack: **React**; the core stays frontend‑agnostic via a contract.
4. Default tenancy: **`organization`**; the core stays tenancy‑agnostic.
5. Secure‑by‑default is **two‑layered where runtime can enforce**: a runtime‑observable
   rule is a fail‑closed runtime control **and** a build‑time test; a source‑form rule
   is build‑time‑only by recorded, per‑rule decision (`runtime.applicability` in the
   Terp Standard catalog, ADR 0084) — never silently.

## Documentation

- **Design:** [`AGENTIC_PLATFORM_DESIGN.md`](AGENTIC_PLATFORM_DESIGN.md) — the
  source of truth for the platform's shape and guarantees.
- **Decisions:** [`docs/decisions/`](docs/decisions/) — the architecture decision
  records (ADRs).
- **Deploying:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — the production
  profile (single-host Docker Compose), environment reference, and operations notes.
- **Changelog:** [`CHANGELOG.md`](CHANGELOG.md) — lockstep platform releases.
- **Working notes:** [`docs/internal/`](docs/internal/) — the living status
  tracker, implementation plan, and design reviews.
- **Contributors & agents:** [`AGENTS.md`](AGENTS.md) and
  [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Status

Terp is in **active early development**: the backend core and seventeen
capabilities are built and gated at 100% line coverage; the frontend packages
are still taking shape. See [`docs/internal/STATUS.md`](docs/internal/STATUS.md) for the live
tracker.

## License

Terp is released under the **Apache License 2.0** — see [`LICENSE`](LICENSE) for
the full text. Copyright 2026 AITT-NL.
