# 0081 — The Terp Standard becomes consumable: attributed findings, self-describing spec, checkable layers

- **Status:** Accepted
- **Date:** 2026-07-07
- **Relates:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md)
  (the catalog + corpus this extends), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer discipline the entries now record), and [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (the escape-hatch semantics the spec now states abstractly).

---

## Context

ADR 0080 extracted the rules as data (`spec/catalog`) plus their executable
meaning (`spec/corpus`), locked to the reference implementation by parity
tests. A review against the actual goal — *a catalog referenced by
stack-specific runners/checkers* — found the contract not yet sound for an
external consumer:

1. Frontend findings were not attributable to catalog rule ids: four catalog
   rules share core ESLint ids (`no-restricted-syntax` × 3,
   `no-restricted-imports` × 2), so the corpus test for one rule would accept a
   finding from another, and a third-party checker could not prove *which*
   rule fired.
2. No machine-readable finding format existed — the catalog said what to
   check but not what a checker must emit.
3. The catalog's schema lived implicitly in `test_spec_catalog.py` and there
   was no spec version to certify against.
4. Entries recorded only `build-time` enforcement, hiding the runtime half of
   the two-layer discipline a Level 3 stack must reproduce.
5. The three `black-box` rules named no black-box probe — the layer existed
   only in prose.
6. Corpus coverage had no ratchet, and portable rules were uncovered.
7. The corpus contract's wording ("no findings at all") did not match the
   per-rule backend harness.
8. The opt-out field baked Python/JS comment syntax into a stack-neutral spec.

## Decision

Make the spec consumable, keeping every artifact parity-locked:

- **Findings attribute to catalog ids.** `@terp/eslint-boundaries` publishes
  `catalogRuleId(message)` — the adapter's `reported_as → catalog id` mapping
  (shared core rule ids are disambiguated by their configured messages, built
  from one source). The frontend corpus harness asserts the catalog id, never
  the raw ESLint id. `spec/findings.schema.json` defines the interoperable
  finding shape (`rule` = catalog id, `path` relative to the checked tree,
  optional `line`/`message`); the corpus contract is stated per rule over it.
- **The spec is self-describing and versioned.** `spec/catalog/schema.json`
  (normative JSON Schema for entries) and `spec/VERSION` travel with the spec;
  the parity test validates every entry against the checked-in schema with a
  dependency-free validator.
- **The two-layer story is recorded.** Where the fail-closed runtime control is
  a distinct named seam, the entry carries a `runtime` enforcement reference
  (`build_guard`, `WriteGuardedSession`, `build_read_only_request_binder`,
  `PaginationParams`, `verifySlotChildren`); the parity test resolves each ref
  against the cited package's sources.
- **The black-box layer is checkable.** `@terp/conformance` gains
  `tests/standard.spec.ts` — portable probes over a running app (Page envelope
  + fail-closed limit cap, safe-method non-mutation, no credential-shaped
  response fields) — and every `layer: black-box` entry must name its probe in
  a `black-box` enforcement entry, resolved by the parity test against the
  suite's test titles.
- **Coverage ratchets.** `spec/corpus/PENDING.json` lists exactly the rules
  still without corpus cases (parity-tested both ways, so the list only
  shrinks visibly); every `static-portable` backend rule must have cases (the
  six uncovered ones are seeded here), and the `opt_out` field is documented
  as the *reference realisation* of the abstract escape-hatch contract
  (justified inline marker + budget ratchet), whose semantics are the
  normative part.

## Consequences

- A second-stack rule pack now has a complete contract: implement the catalog
  (schema-validated, versioned), emit findings per `findings.schema.json`
  attributed to catalog ids, pass the corpus per rule, and — for Level 3 —
  reproduce the named runtime controls and the escape-hatch semantics.
- The `black-box` layer classification is no longer prose: reclassifying a
  rule to `black-box` forces shipping its conformance probe.
- Cost: a new rule without corpus cases must be listed in `PENDING.json`
  explicitly, and a portable backend rule cannot ship uncovered at all.
- The `arch-allow-*` / `terp-allow-*` prefix split stays (renaming markers
  would churn every budget file for no semantic gain); the spec states the
  shared semantics instead.
