# 0092 — Typed route params: a fail-closed read now, generated route types next

- **Status:** Accepted
- **Date:** 2026-08-14
- **Relates:** [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md) (the
  fail-closed refusal shape the stopgap reuses) and the committed-artifact codegen
  pattern established by `terp openapi` + the `api-docs-drift` verify check (the shape
  the full fix will follow).

---

## Context

`buildAppRouter` realises routes at runtime from module manifests. That is the right
seam — the manifest is stack-agnostic data, modules are discovered by glob, and a route
naming a missing view already throws at build time — but it has a type-level cost:
TanStack Router's route registry is generic over a *statically constructed* route tree,
and a runtime-built tree leaves it empty. In every Terp app, therefore:

- no route **path** in `navigate({ to })` is checked — a typo'd path is a dead link
  that ships green;
- no route **param name** is checked anywhere — the idiomatic read is an unchecked
  cast, `useParams({ strict: false }) as { recordId?: string }`, and the framework's
  own admin detail screens carried exactly that cast;
- a probe file exercising all three failure modes (`params.thisParamDoesNotExist`,
  a bogus `navigate` target, a wrong param key) typechecks clean.

That is squarely against the platform's own line that a red typecheck means the app
does not work: this failure mode *cannot go red*. The information needed to close it is
already checked in — `manifest.routes` is static data.

## Decision

Two steps, shipped at different speeds.

**1. `useRouteParam` (shipped first).** The sanctioned param read in
`@terpjs/react-core`: `useRouteParam("recordId")` returns the declared param as a
string and **throws a directive error** — naming the param, the params actually
present, and where params are declared — when the current route did not declare it.
The raw cast silently yields `undefined` and renders a broken screen; the sanctioned
read fails closed at the moment of the mistake, which is the best a runtime check can
do and strictly better than the status quo. The in-tree admin detail screens adopt it,
deleting their casts. It remains the right read for a single param, and step 2 adds the
compile-time check on top of it.

**2. Generated route types (shipped).** The committed-artifact pattern `terp openapi`
established — generate, commit, gate:

- **The generator.** `terp-routes` (a bin from `@terpjs/contract`, which owns the manifest
  contract) parses every `src/modules/<name>/module.tsx` with the TypeScript compiler API,
  reads the `path` literals out of each `defineModuleManifest(...)` call, and writes
  `src/routes.gen.d.ts` — a `declare module "@terpjs/react-core"` augmentation of the
  `TerpRouteTable` interface, mapping each path to its params (`"/records/:recordId"` →
  `{ recordId: string }`). Output is deduped, sorted, LF-only: a committed artifact has to
  diff cleanly to be gate-able. `terp routes` wraps it, and the same command is what
  `terp dev` runs as a preflight beside the OpenAPI export.
- **Consumption.** `useRouteParams("/records/:recordId")` returns that route's params
  exactly; `useRouteParam(name)` is checked against every declared param name;
  `useTerpNavigate()` refuses an undeclared path and requires a parameterised route's
  params, in the manifest's `:id` spelling (it translates to the router's `$id`). With no
  generated file the table is empty, every helper falls back to `string`, and behavior is
  exactly what it was — generating is what turns the checks on.
- **Fail-closed extraction.** A route whose `path` is not a plain string literal (a
  template literal, a constant, a spread) is named with its file and line and the run is
  refused. A partial table is worse than none: it turns a real path into a type error and
  teaches authors to distrust the check.
- **The gate.** `terp-routes --check` re-renders in memory and compares with the committed
  file — no git, so it also catches a hand-edit, and it reports the regeneration command.
  It runs as the `routes-drift` verify check in every profile, ordered **before**
  `frontend-typecheck` because a stale table otherwise surfaces as a pile of type errors
  in the app's own screens when the real fault is one unregenerated artifact.
- **Scope: the app's own manifests.** Routes a packaged area mounts (react-core's admin
  area) are deliberately not keyed, so the artifact is a pure function of the app's own
  source and never drifts because a dependency's internals changed. The packaged screens
  therefore read their own params through an internal untyped helper, not the app-facing
  `useRouteParam` — otherwise an app that declares no params of its own would fail on
  framework code it does not own.
- **Adopt-forward, not break-on-upgrade.** Route types are opt-in for an existing app: with
  no `routes` script wired, the `terp dev` preflight and the `routes-drift` check are
  no-op successes carrying the two-step hint, exactly as `api-docs-drift` is a no-op until
  a project commits `docs/`. The template ships the script, the committed table, and a CI
  step, so new apps are gated from the first commit.

## Consequences

- The failure mode this ADR exists for can now go red: an undeclared path, a param no
  route declares, and a paramless route handed params are all typecheck errors. A
  compile-time assertion in the example app (`src/routeTable.check.ts`) fails if that
  stops being true — the guarantee is itself gated, because its absence is invisible.
- A manifest route change now has a second step: regenerate. That is the cost of the
  check, and it is why the gate reports the exact command rather than only the diff.
- `@tanstack/react-router` stays a direct app dependency; nothing wraps or hides the
  router. The generated types narrow the existing API instead of replacing it.
- `@terpjs/contract` gains `typescript` as a runtime dependency — the generator needs a
  parser, and a hand-rolled scanner could not honestly tell a non-literal path from a
  literal one, which is the fail-closed rule above.
