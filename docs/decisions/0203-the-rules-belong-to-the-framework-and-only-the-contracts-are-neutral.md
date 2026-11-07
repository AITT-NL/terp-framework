# 0203 — The rules belong to the framework, and only the contracts are neutral

- **Status:** Accepted on 2026-11-06 by the owner. Built in 0.38.0: the rules, the
  corpus, the refused surface, the rule pages and the runtime security cases moved here from
  terp-spec 0.43.0, and the scorecards are gone. On 2026-11-07 the owner settled the two
  open points. Decision 3: the contracts are published from their own repository,
  `terp-spec`. The rename is dropped: the package keeps `terp-spec` / `@terpjs/spec`,
  because `@terpjs/contracts` sits one letter from this framework's `@terpjs/contract`. So
  no release points to a new name; terp-spec 0.44.0 is the contracts-only release every
  reader repins to once.
- **Date:** 2026-11-05. 0194 to 0202 are taken.
- **Amends:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md),
  [ADR 0081](0081-terp-standard-consumable-findings-schema-and-layers.md),
  [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md),
  [ADR 0086](0086-publish-the-terp-standard-to-pypi-and-npm.md) and
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) §4, as the
  table below says.
- **Relates:** keeps [ADR 0084](0084-runtime-applicability-classification.md) (runtime
  applicability, per rule) and [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
  decision 5 (a declaration read by two programs lives in a shared package); leans on
  [ADR 0123](0123-marketing-websites-are-not-a-terp-application-kind.md) §1 (the build-time half
  alone is a linter); leaves [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md)
  and ADR 0084's two-stage certification nothing to govern once the rules move; names
  [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md) (the authority baseline)
  and [ADR 0200](0200-a-release-is-signed-only-over-a-green-release-profile.md) (proposed: the
  release gate document) as an app's evidence.

---

## Decision

Terp is a Python and React framework, and making the backend stack-neutral is not a goal. The
rule catalog and its corpus are this framework's own rules: they move into this repository,
split by surface under one id namespace, and every rule keeps its machine-checked runtime
applicability. Only the contracts stay a separate package: the documents that more than one
program reads (the deployment, workbench and layout declarations, the check-report and
findings formats, and the conversation event stream), and the assurance profile, which ADR
0111 decision 5 places with them. That package has no dependencies, is
versioned outside the lockstep, and is renamed `terp-contracts` / `@terpjs/contracts`
*(dropped on 2026-11-07: it keeps `terp-spec`; see Status)*. Another
language or client joins at the edges, as a client of an app's HTTP API or as a declared unit
of its deployment, never as a second kind of Terp app. Terp certifies no app built without it:
scorecards, conformance levels and certification against a pinned reference commit are
withdrawn, and an app's trust artefact is its own per-release evidence.

## Context

ADR 0080 called the standard "the durable product", with this framework as its reference
implementation. ADR 0081 gave a second stack's checker a contract, up to "a Level 3 stack", and
the spec went on to define three conformance levels and a scorecard. ADRs 0082 and 0086 made it
a separate, published package. A review of all four Terp repositories on 2026-11-04 found the
standard is not what those records expected:

- By a per-rule reading of each rule's title and intent (listed in the appendix), 65 of the 105
  rules presuppose this framework's architecture: module manifests, declared policies, one
  audited write path, a composed read query, the escape-hatch budget. 36 are generic, and 11 of
  those overlap a stock ruff or ESLint rule. 4 only mean something in Python. Another reader
  would move a few rules; the majority does not change.
- The backend corpus is Python, apart from the deployment declaration's own cases, and 152 of
  its cases import `terp`. The three black-box probes log in and read through this framework's
  own routes.
- No second implementation exists. The published package is installed only by this
  repository's tests. Studio clones the spec at the tag this repository pins, for rule titles.
  Studio, the runner and `terp-arch` read the declaration schemas as byte copies.
- CI is circular. The spec's CI checks out this repository at a pinned commit, and this
  repository installs the published spec, so a new rule needs a fixed push order across both.

ADR 0123 already named why neutrality cannot carry the value. A kind without the runtime half
"would inherit the build-time half of the model and none of the half that distinguishes this
framework from a linter." A checker can refuse, but it cannot supply the safe construct. An
omission has no place to be found without a declared structure. And static checks have
recorded gaps: 29 forms across 14 rules in `RESIDUALS.json`. Where the running system can
observe a rule, a fail-closed runtime control sees what the check misses. 38 rules have one,
3 of them among those 14; for the other 11, the gap is recorded, not closed.

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
   security scenarios move beside the tests that run them. The contracts package holds the
   documents the decision paragraph lists, the assurance profile among them as ADR 0111
   decision 5 names it, and keeps the spec's isolation: no `terp.*` import and no dependency.
   Whether it is published from its own repository or from this one is decided when the rules
   move.
4. **Other languages and clients join at the edges.** A mobile app, a public site or a service
   in another language is a client of an app's committed API contract, or a declared unit in
   its deployment. Identity, permissions, audit and data stay with the Terp app.
5. **No certification of apps built without Terp.** A checker's certificate on free-form code
   would claim a safety it cannot deliver. The scorecard certifies a checker, not an app, so it
   goes with the conformance levels and `certify-against-reference`. What an app shows instead
   is its own release: the release gate document (ADR 0200, proposed), the assurance profile and
   the authority baseline (ADR 0139).

## What this amends

| ADR | Withdrawn | Kept |
|---|---|---|
| 0080 | The standard as "the durable product", and the second-stack phase in its consequences | The catalog, the corpus, the parity tests, and a rule shipping with its entry |
| 0081 | The contract for a second stack's rule pack, and the "Level 3 stack" it names | Findings attributed to catalog ids, the findings and check-report formats, and the black-box probes as this framework's tests |
| 0082 | A split-ready spec that holds the rules | Consumption as a package, never a path, now applied to the contracts |
| 0086 | `terp-spec` and `@terpjs/spec` as the published names, and publishing gated on `certify-against-reference` | Trusted Publishing, idempotent publish jobs, and pinning by version |
| 0122 | §4's "what a certified toolchain was certified against", and the consequence that the certification flow is unaffected | The breadth freeze, and the assurance lanes with their requirement levels |

## Consequences

- Nothing moves until this record is accepted and terp-spec#52 is released as 0.43.0 with
  this repository repinned to it. Release 0.36.1 (PR #204) brought the runtime security tests
  and their evidence index; #52 brings the ten cases those tests already run ahead of the
  pin. The fixtures and those cases move with the rules.
- The wording changes now. The spec's README, its schema descriptions, its packages'
  descriptions, and both repositories' `AGENTS.md` stop calling the rules stack-neutral.
- The generated rule pages still end their reference text with "another stack ships its own
  realisation". They are regenerated where the rules land.
- Withdrawing the scorecard removes its emitters here: `tools/emit_backend_scorecard.py` and
  `@terpjs/eslint-boundaries`' `scorecard.js`, the steps that run them in `ci.yml`,
  `frontend.yml` and `release.yml`, and the release's attachment of the scorecards
  (`release.yml`, `docs/RELEASING.md`).
- With the rules here, no CI job checks out another repository, and a rule, its check and its
  corpus land in one pull request.
- *(Dropped with the rename on 2026-11-07; see Status.)* The rename costs one migration: a
  last `terp-spec` release points to `terp-contracts`, and
  every reader repins once.

## Alternatives considered

- **Make the standard truly neutral**: a profile of the generic rules, probes defined at the
  HTTP level, a corpus per language and a second checker. Rejected. The portable part mostly
  overlaps stock linters, and certifying it would claim a safety it cannot carry.
- **Drop the spec entirely.** Rejected. Studio and the runner must not import `terp.*`, and the
  contracts are how they read an app.
- **Keep the current layout.** Rejected. The claim is untrue, and the CI loop costs every rule
  change.

## Appendix: the per-rule reading

Generic, adoptable by an app not built on Terp (36): `backend/alembic_downgrades_not_empty`,
`backend/datetime_columns_are_timezone_aware`, `backend/frozen_values_hold_no_mutable_collection`,
`backend/input_str_fields_have_max_length`, `backend/list_routes_paginate`,
`backend/migration_history_is_intact`, `backend/no_blocking_sleep`,
`backend/no_destructive_migrations`, `backend/no_dynamic_sql`, `backend/no_empty_tests`,
`backend/no_eval_or_exec`, `backend/no_exception_text_in_responses`,
`backend/no_hardcoded_credentials`, `backend/no_naive_datetime`,
`backend/no_oversized_python_files`, `backend/no_print`, `backend/no_star_imports`,
`backend/no_todo_fixme`, `backend/no_unique_columns_on_soft_delete_models`,
`backend/not_null_columns_are_backfilled`, `backend/offset_queries_declare_ordering`,
`backend/references_declare_delete_behaviour`, `backend/response_model_not_table_model`,
`backend/routes_declare_response_model`, `backend/safe_methods_are_read_only`,
`backend/schemas_exclude_sensitive_fields`, `frontend/locale-catalogs-complete`,
`frontend/no-deep-imports`, `frontend/no-dom-html-injection`, `frontend/no-eval`,
`frontend/no-raw-clipboard`, `frontend/no-raw-random-uuid`, `frontend/no-unsafe-href`,
`frontend/no-unsafe-target-blank`, `frontend/no-untranslated-ui`, `frontend/router-links`.

Of those, 11 overlap a stock rule, some only in part: `no_eval_or_exec`, `no_print`,
`no_star_imports`, `no_todo_fixme`, `no_naive_datetime`, `no_dynamic_sql`,
`no_hardcoded_credentials`, `no-eval`, `no-unsafe-href`, `no-unsafe-target-blank` and
`no-dom-html-injection`.

Meaningful only in Python (4): `backend/no_dependency_overrides`,
`backend/no_mutable_default_args`, `backend/schemas_avoid_positional_tuples`,
`backend/session_imported_from_sqlmodel`. Of these, `no_dependency_overrides` and
`session_imported_from_sqlmodel` also presuppose the framework's composition, and
`schemas_avoid_positional_tuples` describes a failure any generated API contract can have.

The other 65 presuppose this framework's architecture.
