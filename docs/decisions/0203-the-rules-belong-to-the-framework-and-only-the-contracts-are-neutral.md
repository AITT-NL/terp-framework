# 0203 — The rules belong to the framework, and only the contracts are neutral

- **Status:** Proposed (awaiting review). Nothing is built on this record until it is accepted.
  It sets a direction; each move it describes is a later change of its own, and the first one
  waits for PR #204 and release 0.36.1.
- **Date:** 2026-11-05. 0194 to 0200 are on PR #204, and 0201 and 0202 are claimed on another
  branch.
- **Amends:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md),
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md),
  [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) and
  [ADR 0086](0086-publish-the-terp-standard-to-pypi-and-npm.md), as the table below says.
- **Relates:** keeps [ADR 0084](0084-runtime-applicability-classification.md) (runtime
  applicability, per rule), [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  decision 5 (a declaration read by two programs lives in a shared package),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (the breadth
  freeze and the assurance lanes) and
  [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md) §1 (the build-time half
  alone is a linter); names [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md)
  (the authority baseline) and ADR 0200 (proposed on PR #204: the release gate document) as an
  app's evidence.

---

## Decision

Terp is a Python and React framework, and making the backend stack-neutral is not a goal. The
rule catalog and its corpus are this framework's own rules: they move into this repository,
split by surface under one id namespace, and every rule keeps its machine-checked runtime
applicability. Only the declarations that more than one program reads stay a separate package:
the deployment, workbench and layout declarations, the check-report and findings formats, and
the conversation event stream. That package has no dependencies, is versioned outside the
lockstep, and is renamed `terp-contracts` / `@terpjs/contracts`. Another language or client
joins at the edges, as a client of an app's HTTP API or as a declared unit of its deployment,
never as a second kind of Terp app. Terp certifies no app built without it: scorecards,
conformance levels and certification against a pinned reference commit are withdrawn, and an
app's trust artefact is its own per-release evidence.

## Context

ADR 0080 called the standard "the durable product", with this framework as its reference
implementation. ADR 0081 gave it three conformance levels and a contract for a second stack's
rule pack. ADRs 0082 and 0086 made it a separate, published package. A measurement of all four
Terp repositories on 2026-11-04 found the standard is not what those records expected:

- 65 of the 105 rules presuppose this framework's architecture: module manifests, declared
  policies, one audited write path, a composed read query, the escape-hatch budget. 36 are
  generic, and 11 of those duplicate a stock ruff or ESLint rule. 4 only mean something in
  Python.
- The backend corpus is Python, and 152 of its cases import `terp`. The three black-box probes
  log in and read through this framework's own routes.
- No second implementation exists. The published package is installed only by this
  repository's tests. Studio clones the spec at the tag this repository pins, for rule titles.
  Studio, the runner and `terp-arch` read the declaration schemas as byte copies.
- CI is circular. The spec's CI checks out this repository at a pinned commit, and this
  repository installs the published spec, so a new rule needs a fixed push order across both.

ADR 0123 already named why neutrality cannot carry the value. A kind without the runtime half
"would inherit the build-time half of the model and none of the half that distinguishes this
framework from a linter." A checker can refuse, but it cannot supply the safe construct. An
omission has no place to be found without a declared structure. And static checks have
recorded gaps (29 forms across 14 rules in `RESIDUALS.json`), which the 37 paired runtime
controls exist to close.

## Decisions

1. **Terp is a Python and React framework.** A second backend stack is a separate product, as
   the design document's §1.2 already says. A second frontend stays possible through
   `@terpjs/contract`, `@terpjs/conformance` and the refused-primitive list, all of which live
   here; nothing in this record builds one.
2. **The framework protects; the checker keeps code inside the framework.** A build-time rule
   exists to keep code on the declared path, and the guarantee is the runtime control behind
   that path. Portability is not a reason to admit or keep a rule.
3. **The rules are the framework's; only the contracts are neutral.** The catalog, the corpus,
   `PENDING.json`, `RESIDUALS.json`, `restricted-surface.json` and the rule pages move here:
   the backend half with `terp-arch`, the frontend half with `@terpjs/eslint-boundaries`, under
   one id namespace so Studio's rule matrix and findings attribution keep working. The runtime
   security scenarios move beside the tests that run them. The contracts package keeps ADR 0111
   decision 5's role, and the spec's isolation: no `terp.*` import and no dependency. Whether it
   is published from its own repository or from this one is decided when the rules move.
4. **Other languages and clients join at the edges.** A mobile app, a public site or a service
   in another language is a client of an app's committed API contract, or a declared unit in
   its deployment. Identity, permissions, audit and data stay with the Terp app.
5. **No certification of apps built without Terp.** A checker's certificate on free-form code
   would claim a safety it cannot deliver. The scorecard certifies a checker, not an app, so it
   goes with the conformance levels and `certify-against-reference`. What an app shows instead
   is its own release: the release gate document (ADR 0200, proposed), the assurance profile and
   the authority baseline (ADR 0139). The assurance lanes ADR 0122 decision 4 keeps are
   unchanged; the certification it mentions is what this record withdraws.

## What this amends

| ADR | Withdrawn | Kept |
|---|---|---|
| 0080 | The standard as "the durable product", and the second-stack phase in its consequences | The catalog, the corpus, the parity tests, and a rule shipping with its entry |
| 0081 | The three conformance levels, the second-stack rule pack contract, and certification by scorecard | Findings attributed to catalog ids, the findings and check-report formats, and the black-box probes as this framework's tests |
| 0082 | A split-ready spec that holds the rules | Consumption as a package, never a path, now applied to the contracts |
| 0086 | `terp-spec` and `@terpjs/spec` as the published names, and publishing gated on `certify-against-reference` | Trusted Publishing, idempotent publish jobs, and pinning by version |

## Consequences

- Nothing moves until this record is accepted and PR #204 is released as 0.36.1. That release
  brings the runtime security fixtures and the ten cases parked in terp-spec#52, which move
  with the rules.
- The wording changes now. The spec's README, its catalog schema, its packages' descriptions,
  and both repositories' `AGENTS.md` stop calling the rules stack-neutral.
- The generated rule pages still end their reference text with "another stack ships its own
  realisation". They are regenerated where the rules land.
- With the rules here, no CI job checks out another repository, and a rule, its check and its
  corpus land in one pull request.
- The rename costs one migration: a last `terp-spec` release points to `terp-contracts`, and
  every reader repins once.

## Alternatives considered

- **Make the standard truly neutral**: a profile of the generic rules, probes defined at the
  HTTP level, a corpus per language and a second checker. Rejected. The portable part mostly
  repeats stock linters, and certifying it would claim a safety it cannot carry.
- **Drop the spec entirely.** Rejected. Studio and the runner must not import `terp.*`, and the
  contracts are how they read an app.
- **Keep the current layout.** Rejected. The claim is untrue, and the CI loop costs every rule
  change.
