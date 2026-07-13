# Copilot instructions — Terp

Instructions for AI coding agents working on the **Terp** platform itself — the
maintained core, the opt‑in capabilities, and the enforcement harness.

## Enforced invariants

Enforced by fail‑closed runtime controls **and** build‑time tests — never weaken
a guard to make a change pass:

| Vector | Guard |
|---|---|
| `terp.core` layer‑0 boundary (imports nothing above itself) | [tests/architecture/test_core_boundary.py](../tests/architecture/test_core_boundary.py) |
| Placeholder namespace regressions | [tests/guardrails/test_no_placeholder_namespace.py](../tests/guardrails/test_no_placeholder_namespace.py) |

## Terp conventions

- **Namespace `terp.*`** (never `platform.*`). Modules import only the
  `terp.core` public surface + their declared capabilities — never
  `terp.core._internal`, never a sibling module.
- **Base classes** — `BaseTable`, `BaseSchema` / `BaseUpdateSchema`,
  `BaseService`. Don't redeclare `id` / `created_at` / `updated_at` / `version`.
- **Secure by default** — declare a `ModuleSpec` with a `Policy`; routers mount
  behind a deny‑by‑default guard. Raise typed `AppError`s; paginate lists
  (`Page[T]`); cap every `str` field's length.
- **Two‑layer enforcement** — a rule whose invariant is observable at runtime is
  a fail‑closed runtime control *and* a build‑time test; never make the test the
  only control for such a rule. A source‑form rule is build‑time‑only by recorded
  decision: the Terp Standard catalog classifies every rule
  (`runtime.applicability`, ADR 0084) and tests fail closed on a missing or
  contradictory classification.

## Frontend conventions

Frontend UI composes the **`@terp/react-core` component surface** — see the catalog in
[packages/frontend/react-core/README.md](../packages/frontend/react-core/README.md).
Enforced by `@terp/eslint-boundaries` (strict-only, no modes — ADR 0059): token‑styled
primitives only (no raw `<button>`/`<input>`/`<select>`/`<textarea>`/`<table>`/`<dialog>`/
`<form>`), the generated client only (no raw `fetch` / `XMLHttpRequest` / `WebSocket` /
`EventSource` / `sendBeacon`), data collections via `DataView`
([dataview README](../packages/frontend/react-core/src/dataview/README.md)),
design‑token styling (`style`, `className` and module stylesheets are refused in app
modules — layout via `Stack` / the page archetypes), in-app links via the router (no raw
`<a href="/...">`), every routed view framed by a page archetype (refused at runtime
otherwise), optional slot-typed layout contracts (ADR 0079: a checked-in
`layout-contract.json` + `layoutContract` at bootstrap constrain each archetype's body
slot to the contract's components, enforced by the `terp/layout-contract` lint half and
a fail-closed runtime DOM check — recipe: `terp guide layouts`),
`UiText` text props, no deep imports, and frontend security defaults
(`dangerouslySetInnerHTML` / DOM HTML-injection sinks / `eval()` / `javascript:` URLs
are refused; static `target="_blank"` needs `rel="noopener"` — use `Markdown` for rich
text). The one governed opt-out is a justified
`// terp-allow-<rule>: <reason>` marker counted against the app's `escape-hatch-budget.json`.

Source of truth: [AGENTIC_PLATFORM_DESIGN.md](../AGENTIC_PLATFORM_DESIGN.md);
decisions in [docs/decisions/](../docs/decisions/). The stack-neutral rule
catalog + violation corpus (the Terp Standard, ADRs 0080/0081) lives in
[AITT-NL/terp-spec](https://github.com/AITT-NL/terp-spec) — a new rule ships
with a catalog entry there, and corpus cases shrink its `corpus/PENDING.json`.
The spec is consumed as a package (`terp-spec` / `@terp/spec`, pinned by
release tag — ADR 0082), never a repo-relative path.
Run the gate with `uv run pytest`.
