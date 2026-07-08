# 0082 — Repo-split readiness: the spec becomes a package, coupling becomes dependencies

- **Status:** Accepted
- **Date:** 2026-07-08
- **Relates:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) /
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md) (the
  spec this packages) and the studio isolation discipline (`studio/README.md`,
  the precedent this generalises).

---

## Context

The monorepo hosts three units with different lifecycles: the **framework**
(the reference implementation — `packages/`, `tests/`, `apps/`, `template/`),
the **Terp Standard** (`spec/` — stack-neutral data, versioned independently),
and **Terp Studio** (`studio/` — already fully decoupled: no `terp.*` imports,
its own tests and path-filtered CI). The intent has always been that any of
them can split into its own repository.

Studio met that bar; the spec did not. Although the spec's *data* was
self-contained, its consumers located it by repo-relative path:
`tests/architecture/test_spec_catalog.py` / `test_spec_corpus.py` computed
`_REPO_ROOT / "spec"`, and the ESLint adapter's `corpus.test.js` /
`surface.test.js` resolved `../../../../spec`. A split would have required
code edits in the framework, and the spec's self-consistency checks
(schema validity, versioning, the corpus ratchet) lived inside the framework's
test tree — a spec-only repository would have had no CI of its own.

## Decision

Make coupling a **declared dependency**, never a path, so a repository split is
purely a manifest change (workspace source → git/registry pin):

1. **`spec/` is packaged twice over one data directory.** A `terp-spec` Python
   distribution (uv workspace member; a dependency-free `terp_spec` accessor
   exposing `spec_dir()` / `spec_version()`, with the data force-included into
   the wheel) and a private `@terp/spec` npm workspace member (data only,
   resolved via `require.resolve("@terp/spec/package.json")`). Both carry the
   **spec version** (`spec/VERSION`), deliberately outside the platform's
   lockstep release version — a checker certifies against a spec version
   (ADR 0081), and the spec's own suite holds the three declarations equal.
2. **Consumers go through the seam.** The framework certification tests import
   `terp_spec` (declared in the dev dependency group); the ESLint adapter tests
   resolve `@terp/spec` (a devDependency). No repo-relative escapes remain.
3. **The spec CIs itself.** The spec-only validations (versioning, schema
   validity of every catalog entry, the finding format, the refused surface's
   shape and citation coverage, the corpus ratchet and directory discipline)
   moved to `spec/tests/` — standalone, dependency-free (pytest only) — run by
   a path-filtered `spec.yml` workflow mirroring `studio.yml`. The framework
   gate keeps only the parity assertions that need the live implementations
   (rule registry ↔ catalog, ESLint adapter ↔ catalog, runtime/black-box refs,
   corpus certification), which still run on every push — a spec change that
   breaks parity fails the monorepo gate today and pins fail tomorrow's split
   repos the same way.
4. **Readiness is enforced, not aspirational.**
   `tests/architecture/test_repo_split_readiness.py` fails the build if
   framework code constructs a path into `spec/`, references `studio/` at all,
   if `terp-spec` grows dependencies or `terp.*` imports, or if studio joins a
   workspace.

## Consequences

- Splitting **studio** = move `studio/` + `studio.yml`. Splitting **spec** =
  move `spec/` + `spec.yml`, then repin `terp-spec` / `@terp/spec` from
  workspace sources to a git tag or registry release — zero code edits. The
  **framework** is the remainder.
- The spec version (0.3.0) and the platform release version (0.1.0) are now
  visibly independent artifacts; `test_release_versions` deliberately does not
  sweep `spec/`.
- Publishing `terp-spec` / `@terp/spec` to registries stays out of scope until
  a split actually happens; workspace resolution is sufficient inside the
  monorepo.
