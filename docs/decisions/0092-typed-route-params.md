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

**1. `useRouteParam` (shipped with this ADR).** The sanctioned param read in
`@terpjs/react-core`: `useRouteParam("recordId")` returns the declared param as a
string and **throws a directive error** — naming the param, the params actually
present, and where params are declared — when the current route did not declare it.
The raw cast silently yields `undefined` and renders a broken screen; the sanctioned
read fails closed at the moment of the mistake, which is the best a runtime check can
do and strictly better than the status quo. The in-tree admin detail screens adopt it,
deleting their casts.

**2. Generated route types (the full fix, next).** Follow the committed-artifact
pattern `terp openapi` established — generate, commit, gate the diff:

- a generator extracts each module manifest's route literals (`defineModuleManifest`
  calls under `src/modules/*/module.tsx`) and emits a committed
  `src/routes.gen.d.ts`: a `TerpRouteParams` interface mapping each route path to its
  param object (`"/syncs/:syncId"` → `{ syncId: string }`);
- `useRouteParam` and a typed navigation helper pick the types up via interface
  augmentation, so a wrong path or param name goes red in any app that generated;
- drift is gated, not trusted: a verify check diffs the regenerated artifact, exactly
  like `api-docs-drift`, and `terp dev` regenerates as a preflight;
- extraction is fail-closed: the manifests are data, but they live in TypeScript, so
  the generator refuses (lists, does not skip) a route whose path is not a string
  literal rather than silently emitting a partial map.

The generator is deliberately **not** shipped in the same change as the stopgap: it
needs a TS-extraction seam, template wiring, and a verify check, and rushing those in
one batch is how a half-right contract ships. This ADR records the design so the next
change implements it against a decided shape.

## Consequences

- Route params stop being silently wrong today (`useRouteParam` throws where the cast
  guessed), and stop being a runtime concern at all once the generated map lands.
- Until step 2 lands, `navigate({ to })` paths remain unchecked — the stopgap
  deliberately covers only the param read, which is where both in-tree casts and both
  reported app-side casts lived.
- `@tanstack/react-router` stays a direct app dependency; nothing here wraps or hides
  the router. The generated types narrow the existing API instead of replacing it.
