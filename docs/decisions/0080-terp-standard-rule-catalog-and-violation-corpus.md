# 0080 — The Terp Standard: rule catalog and violation corpus

- **Status:** Accepted
- **Date:** 2026-07-07
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer enforcement shape every rule keeps), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (the governed opt-out both surfaces share), and the "docs can't lie" parity
  discipline ([ADR 0030](0030-agent-surface-completeness-and-docs-parity.md) and
  `tests/architecture/test_docs_parity.py`).

---

## Context

Terp's thesis is that agent-written codebases need fail-closed guardrails more
than they need any particular framework. Today those guardrails — ~40 backend
`terp.arch` rules, the frontend boundary rules, and their runtime halves — exist
only *as* the reference implementation (Python/FastAPI + React). Their meaning
is embedded in tool code, so another stack cannot claim (or be verified for)
conformance, and the rules cannot outlive the tools that currently enforce them.

The strategic direction: the durable product is a **standard** — the rules as
data plus an executable definition of what each rule means — with the framework
in `packages/` as its reference implementation. This ADR ships the first two
extraction steps.

## Decision

Create a self-contained `spec/` directory (no `terp.*` imports, split-ready like
`studio/`) holding two artifacts:

1. **The rule catalog** (`spec/catalog/<surface>/<rule>.json`): one JSON entry
   per enforced rule — id, title, intent, enforcement-layer classification
   (`black-box` / `static-portable` / `static-bespoke`, a judgment of the
   cheapest faithful verification for a *new* stack), the reference
   implementation's enforcement entry point, the governed opt-out, and (backend)
   the `terp guide` fix topic. Every `terp.arch` rule (including the two budget
   rules) and every frontend boundary rule (the named `terp/*` rules plus the
   `BOUNDARY_SPEC` families) is catalogued.

2. **The violation corpus** (`spec/corpus/<surface>/<rule>/`): per rule,
   `violation-*` and `compliant-*` sample trees. The conformance contract for
   any checker: flag every violation case for that rule, report nothing on any
   compliant case. Seeded for the portable security rules on both surfaces;
   coverage grows by convention (add cases, flip the entry's `corpus` flag).

Both artifacts are locked to the live implementations, in both directions:

- `tests/architecture/test_spec_catalog.py` — a rule cannot ship without a
  catalog entry, an entry cannot outlive its rule, enforcement refs must
  resolve, guide topics must match, and the `corpus` flag must match the
  directories on disk.
- `tests/architecture/test_spec_corpus.py` — every catalogued `terp.arch` rule
  passes its own corpus.
- `packages/frontend/eslint-boundaries/src/corpus.test.js` — the ESLint adapter
  passes the frontend corpus.

Corpus samples are deliberate violations, never imported or executed; they are
excluded from the repo-wide ruff security backstop (`extend-exclude`).

## Consequences

- "Terp-conformant" acquires a testable meaning independent of the reference
  stack: the corpus is the acceptance test for any future rule pack (Semgrep /
  ast-grep realisations for other languages) and the catalog is what such a
  pack implements.
- The parity tests extend the gate's existing completeness discipline to the
  spec — the standard cannot silently drift from what is actually enforced.
- Later phases build on this seam: a standalone black-box conformance runner
  (the `black-box` layer), a second-stack rule pack certified against the
  corpus (the `static-portable` layer), and eventually a repo split of `spec/`.
- Cost: adding a rule now requires its catalog entry in the same change (the
  gate fails otherwise) — deliberate, mirroring how `GUIDE_TOPIC_BY_RULE`
  already forces a fix recipe per rule.
