# 0086 — Publish the Terp Standard to PyPI and npm

- **Status:** Accepted
- **Date:** 2026-07-27
- **Relates:** [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) (the
  package seam this completes) and
  [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) /
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md) (the
  standard being distributed).

---

## Context

ADR 0082 packaged the spec twice over one data directory — a `terp-spec` Python
distribution and a private `@terp/spec` npm package — so that coupling became a
declared dependency instead of a repo-relative path. It deliberately deferred
registry publishing: *"Publishing `terp-spec` / `@terp/spec` to registries stays
out of scope until a split actually happens; workspace resolution is sufficient
inside the monorepo."* The spec has since moved to
[AITT-NL/terp-spec](https://github.com/AITT-NL/terp-spec), and both consumers
repinned to a release **tag** — the migration path the ADR anticipated
("workspace sources to a git tag **or registry release**"). Its own precondition
is therefore met, and `tests/test_release_workflow.py` in the spec repository
carries the matching tripwire (`test_release_workflow_stays_registry_free`:
"revisit the ADR before adding it").

Three things now argue for finishing the seam rather than leaving it at tags:

1. **The git pin is on a deprecation clock.** npm 12 refuses git-type
   dependencies outright (`EALLOWGIT`). This already broke the framework's
   v0.2.0 release: the `publish-npm` job is the only one that upgrades npm (a
   Trusted Publishing prerequisite), so it was the first to meet npm 12 and
   could only be rescued with `npm ci --omit=dev`. Every other workflow
   (`ci.yml`, `frontend.yml`, `conformance.yml`, and the release's own `verify`
   job) runs a plain `npm ci` and *needs* the dev tree — the corpus and surface
   tests are exactly what resolves `@terp/spec`. When the runner image ships
   npm 12, those break with no `--omit=dev` escape.
2. **A standard needs a distribution channel.** ADRs 0080/0081 define the
   catalog, corpus, findings envelope and refused surface as *stack-neutral*
   artifacts that a third-party checker implements and is certified against. A
   git tag is a source location; a registry release is how anyone outside this
   organisation consumes a specification and pins it reproducibly.
3. **Registry artifacts carry integrity metadata.** Tarballs resolve by
   integrity hash and (on npm, under Trusted Publishing) carry provenance
   attestations, replacing a lockfile entry that records
   `git+ssh://git@github.com/…` and couples installation to GitHub availability
   and SSH resolution.

## Decision

Publish both distributions from the spec repository's own tag-triggered release
workflow, as part of the same fail-closed sequence that already governs a spec
release.

1. **The npm package is renamed `@terpjs/spec`.** The `@terp` scope is not ours
   — the framework's four frontend packages already publish under `@terpjs/*`,
   and the spec joins them rather than introducing a second scope. Only the
   manifest name changes; the data, the layout and the resolution idiom are
   untouched (`require.resolve("@terpjs/spec/package.json")`). The Python
   distribution keeps its name, `terp-spec`.
2. **Both registries publish via Trusted Publishing (OIDC).** No long-lived
   token is stored in either repository — the same posture as the framework's
   lockstep release.
3. **Publishing is gated on certification, and the GitHub Release is gated on
   publishing.** The publish jobs require `verify` *and*
   `certify-against-reference`, so a version that no conformant checker exists
   for can never reach a registry; the Release job requires the publish jobs, so
   a Release never announces a version the registries do not have. Both jobs are
   idempotent (`skip-existing` on PyPI, an `npm view` guard on npm) so a partial
   release is re-runnable.
4. **Consumers pin by version, not by tag.** The framework's `[tool.uv.sources]`
   git entry and the boundary package's `github:AITT-NL/terp-spec#<tag>`
   devDependency both become ordinary version pins. The `--omit=dev` workaround
   in the framework's `publish-npm` job is removed with them.
5. **The version contract is unchanged.** The distribution version *is* the spec
   version (ADR 0082) — publishing adds a channel, not a cadence.

## Consequences

- The spec's release workflow grows two publish jobs and stops being
  registry-free; `test_release_workflow_stays_registry_free` is replaced by a
  test asserting the publishing contract above (fail-closed ordering, OIDC
  permissions, idempotency).
- **One manual bootstrap is unavoidable on npm.** A trusted publisher is
  configured on a package's settings page, so the package must already exist:
  the first `@terpjs/spec` publish is a one-time authenticated `npm publish`,
  after which every release flows through OIDC. PyPI has no such gap — a
  *pending* publisher can be configured for a project that does not yet exist,
  so `terp-spec` is OIDC-published from its very first upload.
- The rename is a two-step migration across repositories: the spec ships the new
  name first (its certification step substitutes the checkout for **both** scope
  paths during the transition), the framework repins afterwards, and the legacy
  `@terp/spec` leg is dropped once no consumer resolves it.
- The git-tag pin remains valid for anyone who wants it — publishing adds a
  channel without removing the source-level one.

## Alternatives considered

- **Keep the git pins.** Rejected: npm 12 removes the mechanism, and the escape
  that saved the v0.2.0 release does not generalise to the workflows that need a
  dev tree.
- **Pin the npm side to a remote tarball URL** (`codeload…/tar.gz/refs/tags/v*`),
  which npm still permits because it is not a git-type dependency. Rejected as a
  durable answer: it sidesteps `EALLOWGIT` but keeps installation coupled to
  GitHub availability, provides no registry integrity or provenance story, and
  leaves the standard undiscoverable. It remains a valid emergency stopgap.
- **Claim the `@terp` npm scope.** Not available; splitting the organisation's
  packages across two scopes would be worse than a one-time rename.
- **Vendor the spec back into the framework.** Rejected — it re-couples the two
  units by path, which is exactly what ADR 0082 removed.
