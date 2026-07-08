# 0019 - Agent-onboarding & discoverability model

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 → Phase 5/6 direction (agent experience)
- **Relates:** [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md) §9
  (agent-experience) + §10 (agent-visibility); [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (two-layer enforcement — the gate as tutor).

---

## Context

Terp will be **published** and used heavily by **agentic coders**. By default an agent
works inside the **consumer** repo and does **not** read third-party libraries
(`.venv` / `site-packages`), so the framework's instructions must either **live in the
consumer repo** or be **reachable by a command the agent is told to run**. A single
static "manual" is the wrong shape: it rots, and agents do not go looking for it in
`site-packages`.

The design already commits to the right pieces (§9 / §10): a vendored read-only core,
an instruction pack that travels in the client repo, a generated API contract, the CLI,
and the pedagogical gate. This ADR turns that into a **concrete, ranked model** and
ships the first slice.

## Decision

Adopt a **layered** onboarding model — channels ranked by how reliably an agent uses
them — under two principles: **(a) generated + parity-tested over hand-written**, and
**(b) the always-read pointer (`AGENTS.md`) stays terse and DRY**, pointing at the live
surface (`terp guide`) instead of duplicating it.

Channels, highest-reliability first:

1. **Consumer `AGENTS.md`** — the bootstrap pointer agents read by default: the golden
   rules + "run `terp guide` / the gate."
2. **The `terp` CLI as a live instruction surface** — `terp guide [topic]`,
   `terp inspect`, `terp check`, `terp new module`, `terp api-docs`. Deterministic; an
   agent runs it and reads stdout; no third-party reading.
3. **Generated `docs/platform-api.md` + `.pyi`** — the contract, generated from the
   live control-plane / `ModuleSpec` / rules registries.
4. **Vendored read-only `vendor/terp-core/`** — monorepo-level source visibility;
   CODEOWNERS + `test_vendored_core_unmodified` keep it read-only.
5. **The arch gate as tutor** — fixable failure messages (already shipped).
6. *(optional)* a packaged **skill / MCP server** for native agent environments
   (Copilot skills, Claude MCP) — the most native integration, but environment-specific.

**Shipped now (the first slice):**

- **`terp guide [topic]`** — a curated, deterministic authoring guide: an overview, the
  golden rules the gate enforces, and copy-pasteable recipes for `module` / `service` /
  `policy` / `tenancy` / `events` / `capability`.
- **`template/AGENTS.md`** — the consumer bootstrap pointer.

**Discipline:** each new feature ships its `terp guide` recipe **and** its `AGENTS.md`
rule line, kept honest by a future **"docs can't lie" parity test**; generated surfaces
(`terp api-docs`, the rules list) **introspect** the live control plane / `ModuleSpec` /
`_ALL_RULES` rather than being hand-maintained.

## Consequences

- An agent can **self-onboard** from inside a consumer repo: read `AGENTS.md` → run
  `terp guide` → write a module → run the gate (which names any fix).
- Writing the guide is a **forcing function** that surfaces ergonomic smells and feeds
  the roadmap: the repeated CRUD boilerplate → **`build_crud_router`** (Tier-C); the
  "never return the table model" caveat → **H3**.
- The full agent-experience layer (`terp api-docs`, `terp new module`, the copier
  template, the vendored core + parity test, an optional skill / MCP) remains Phase 5/6,
  now sequenced in [docs/STATUS.md](../internal/STATUS.md).
- 321 tests, 100% framework line coverage.
