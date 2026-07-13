# AGENTS.md — Terp

Instructions for **all** AI coding agents (Copilot, Claude, Cursor, Codex, …)
working in this repository. Read this before any non‑trivial change.

## What Terp is

Terp ("Trusted Enterprise Reinforced Platform") is a secure‑by‑default,
agent‑friendly application platform: a maintained core (`terp.core`) + opt‑in
capabilities (`terp.capabilities.*`) + client modules. Source of truth:
[AGENTIC_PLATFORM_DESIGN.md](AGENTIC_PLATFORM_DESIGN.md); decisions in
[docs/decisions/](docs/decisions/).

## Enforced invariants

Enforced by fail‑closed runtime controls **and** build‑time tests — never weaken
a guard to make a change pass:

| Vector | Guard |
|---|---|
| `terp.core` layer‑0 boundary (imports nothing above itself) | [tests/architecture/test_core_boundary.py](tests/architecture/test_core_boundary.py) |
| Placeholder namespace regressions | [tests/guardrails/test_no_placeholder_namespace.py](tests/guardrails/test_no_placeholder_namespace.py) |

## Conventions

1. **Namespace `terp.*`** (never `platform.*`, never `agentic_platform.*`).
   Modules import only the `terp.core` public surface + their declared
   capabilities — never `terp.core._internal`, never a sibling module.
2. **Use the base classes** — `BaseTable`, `BaseSchema` / `BaseUpdateSchema`,
   `BaseService`. Don't redeclare `id` / `created_at` / `updated_at` / `version`.
3. **Secure by default** — declare a `ModuleSpec` with a `Policy`; the framework
   mounts routers behind a deny‑by‑default guard. Raise typed `AppError`s (uniform
   envelope). List endpoints paginate (`Page[T]`). Every `str` field caps length.
4. **Two‑layer enforcement where runtime can enforce** — a rule whose invariant
   the running system can observe pairs its build‑time check with a fail‑closed
   *runtime* control, and the test is never the only control for it. Which rules
   that is, is not folklore: every Terp Standard entry carries a machine‑checked
   `runtime.applicability` classification (`required` / `not-applicable` /
   `deferred`, ADR 0084) — a source‑form rule is build‑time‑only by recorded
   decision, with its rationale in the catalog.
5. **Own per-row writes with a trait** — never hand-roll an `owner_id` check; compose
   `OwnedMixin` for per-row write authorization (the `no_manual_ownership_checks` rule
   enforces it). Detail: `terp guide ownership`.

## Frontend conventions

Frontend UI composes the **`@terp/react-core` component surface** — the catalog lives
in [packages/frontend/react-core/README.md](packages/frontend/react-core/README.md)
(providers, page archetypes, data, feedback, form primitives). Key rules, enforced by
`@terp/eslint-boundaries`:

- **Token-styled primitives only** — never raw `<button>` / `<input>` / `<select>` /
  `<textarea>` / `<table>` / `<dialog>` / `<form>`; use `Button` / `Input` / `Select` /
  `Textarea` / `DataView` / `ConfirmDialog` / `Stack as="form"`.
- **Generated client only** — never raw `fetch`; use `useTerpClient()` + `unwrap`.
  `XMLHttpRequest` / `WebSocket` / `EventSource` / `navigator.sendBeacon` are refused
  on the same footing — one typed egress path.
- **Data collections render via `DataView`** (repository-driven; see
  [packages/frontend/react-core/src/dataview/README.md](packages/frontend/react-core/src/dataview/README.md)).
- **Design tokens, not inline colours**; user-facing text props are `UiText`.
- **No `style={}`, no `className`, no module-authored stylesheets in app modules** — layout
  comes from the react-core primitives (`Stack`, `DetailList`, the page archetypes); theming
  from the token source.
- **Every routed view renders a page archetype** (`Page` / `OverviewPage` / `DetailPage` /
  `HubPage`) — `buildAppRouter` refuses an unframed view at runtime, fail closed.
- **Slot-typed layout contracts (opt-in, ADR 0079)** — an app that checks in a
  `frontend/layout-contract.json` (and passes `layoutContract` to `renderTerpApp`) ratchets
  further: each archetype's body slot accepts only the contract's components (hub bodies:
  `HubCard`; overview bodies: `DataView` / `ResourceList` + framework states; detail bodies:
  `DetailList` / `Stack` / `Tabs` + framework states), enforced two-layer (the
  `terp/layout-contract` lint half + a runtime DOM check, fail closed) with one directive
  message that states the fix. The plain `Page` stays unconstrained; recipe:
  `terp guide layouts`.
- **In-app links go through the router** — never a raw `<a href="/...">`.
- **Security defaults** — `dangerouslySetInnerHTML` and DOM HTML-injection sinks
  (`innerHTML` / `outerHTML` / `insertAdjacentHTML` / `document.write`) are refused
  (use `Markdown` for rich text); `eval()` / `new Function()` are refused;
  `javascript:` URLs are refused; static `target="_blank"` links need `rel="noopener"`.
- **No deep imports** — import from the `@terp/*` package root only.
- **No modes, no severity dial** (ADR 0059) — every boundary violation is an error. The one
  governed opt-out is a justified `// terp-allow-<rule>: <reason>` marker whose counts must
  exactly match the app's checked-in `escape-hatch-budget.json` (a ratchet, run by
  `npm run lint`).

## The Terp Standard (terp-spec)

The stack-neutral specification of the enforced rules lives in its own
repository — [AITT-NL/terp-spec](https://github.com/AITT-NL/terp-spec)
(ADRs 0080/0081): `catalog/` declares every backend + frontend rule as JSON,
`corpus/` holds violation/compliant samples per rule (`corpus/PENDING.json`
is the coverage ratchet — it only shrinks), and `findings.schema.json` is the
finding format a conformant checker emits (attributed to catalog ids). A new
rule must ship its catalog entry; new corpus cases flip the entry's `corpus`
flag and drop the rule from the ratchet. Parity is enforced by
`test_spec_catalog` / `test_spec_corpus` and `corpus.test.js`.

The spec is consumed as a **package**, never a repo-relative path (ADR 0082):
Python via `terp_spec.spec_dir()` (the `terp-spec` distribution, pinned by
release tag in `[tool.uv.sources]`), JS via `@terp/spec` resolution (pinned in
`packages/frontend/eslint-boundaries`). Bump both pins together to adopt a new
spec release; `test_repo_split_readiness` fails the build if framework code
re-couples to `spec/` or `studio/` by path.

## Run the gate

```bash
uv run pytest          # preferred (syncs the workspace)
# without uv (use .venv/Scripts/python on Windows):
python -m venv .venv && .venv/bin/python -m pip install pytest httpx -e packages/backend/core
.venv/bin/python -m pytest
```
