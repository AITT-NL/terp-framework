# 0063 - Lockstep release + publish pipeline and the template acceptance gate

- **Status:** Accepted
- **Date:** 2026-07-03
- **Context phase:** Phase 6 follow-up (the deferred "dist-only publish" note) + the
  copier template's self-sufficiency (Phase 5)
- **Relates:** [ADR 0039](0039-scaffolding-cli-and-copier-template.md) (the template
  this makes deployable), [ADR 0062](0062-production-deployment-profile.md) (the images
  this publishes), [ADR 0034](0034-agent-visibility-vendored-core-mirror.md) (the
  consume-not-fork posture publishing completes)

---

## Context

Terp's whole product posture is "clients **consume** the platform as dependencies" —
yet nothing was consumable: every npm package was `"private": true, "version": "0.0.0"`,
the Python distributions resolved only through the monorepo's uv workspace sources, and
there was no release workflow, no changelog, and no versioning strategy. The copier
template was **broken outside the monorepo**: a generated repo depends on `terp-core` /
`@terp/react-core@^0.1.0`, which existed on no index. Nothing failed when a change broke
the generated-repo path, because nothing exercised it.

## Decision

**One platform, one version, one tag — and a CI acceptance test that consumes Terp the
way a client does.**

1. **Lockstep versioning:** every backend distribution and every frontend package
   carries the same version (now `0.1.0`); a release is one tag `v<version>`. The
   build-time guard is `tests/architecture/test_release_versions.py` (all versions
   equal, npm packages publishable with `publishConfig.access: public`, the version
   recorded in `CHANGELOG.md`) — a partial or drifted release fails the gate, not the
   publish. `CHANGELOG.md` is the human-facing summary; the ADR log stays the rationale
   trail.
2. **`release.yml` on tag:** a `verify` job (tag ↔ version match + the full gate) fans
   out to three publish jobs — PyPI via **trusted publishing** (OIDC, no long-lived
   token) for all backend wheels/sdists; npm (public, `--provenance`) for
   `@terp/contract`, `@terp/eslint-boundaries`, `@terp/react-core`,
   `@terp/conformance`; and GHCR for the production images (ADR 0062) with provenance
   attestation.
3. **Template acceptance job (`template-acceptance` in `ci.yml`):** on every push, CI
   renders the copier template into a temp directory, stages **local wheels** for every
   terp distribution (`uv build`, standing in for the published index via
   `UV_FIND_LINKS`) and **packed npm tarballs** (`npm pack`), then runs the generated
   project's own gate (`uv sync && uv run pytest`) and builds its frontend
   (`typecheck` + `vite build`) against those artifacts. This converts "a generated
   repo works outside the monorepo" from an opinion into a failing test — its first run
   caught a real bug (the template's module shipped a table model with **no
   migration**, so a generated repo's own `tables_have_migrations` gate failed; the
   template now ships a templated first revision).

## Consequences

- Publishing is one `git tag v0.1.x && git push --tags` away once the PyPI trusted
  publisher and `NPM_TOKEN` are configured; until then the acceptance job already
  proves the artifacts install and work.
- The template's `^0.1.0` pins are now real: they match the lockstep version by test,
  and the acceptance job resolves them from staged artifacts exactly as a client would
  from the index.
- Version bumps touch every manifest in one commit (the gate enforces it); per-package
  independent versioning is explicitly rejected for now — revisit only if a package
  needs to break compatibility alone.
- The npm packages currently publish TypeScript-source exports (no dist build step);
  consumers compile them via their bundler exactly as the workspace apps do today. A
  compiled `dist/` publish is a follow-up if a non-Vite consumer appears.
