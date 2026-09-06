# 0119 — A module owes tests, and the Standard recognises two places to keep them

- **Status:** Accepted
- **Date:** 2026-09-06
- **Relates:** [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) (the
  catalog/implementation parity contract this adds a rule to),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced, escapable by proof — this decides what "one pattern" governs here),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (flexibility is
  bounded by legibility, which is the test the second recognised layout has to pass),
  [ADR 0116](0116-a-rule-may-run-ahead-of-its-published-catalog-entry.md) (the allowance that
  lets the rule land here before its catalog entry is published)

---

## Context

`canonical_module_shape` requires five files — `models.py`, `schemas.py`, `service.py`,
`router.py`, `module.py` — and not one of them is a test. No rule in the backend catalog
references a test directory at all, so a module could pass every structural rule in the
Standard, mount routes, own a table and declare a policy, while shipping no tests of any
kind.

That is worse than an omission, because of what sits next to it: `terp scaffold` writes
exactly those five files and stops. An untested module was not a corner an application had
to cut — **it was the shape the platform handed out**. The gate then agreed with it, which
is the part that makes this a Standard problem rather than a habit problem.

The nearest existing rule is `no_empty_tests`, and it only sharpens the point: the Standard
has an opinion about whether a test that exists can fail, and no opinion about whether one
exists.

**The decision this needed was not "are tests required".** That was never in doubt. It was
*where a module's tests live*, and there the two answers already in the field disagreed. A
consuming application had converged on a per-module package under the project's `tests/`;
this repository's own reference application uses one flat `tests/` directory with names like
`test_notes_api.py`. Picking either one and enforcing it makes the other wrong, and the
version of this entry that sat on the backlog recorded the consequence as a blocker: a rule
demanding a per-module directory would make all four of the reference application's modules
non-conformant on the day it landed, and `terp scaffold` would have to emit whichever shape
won or every generated module would be born failing.

## Decision

**A new backend rule, `modules_ship_tests`:** every directory under `modules/` that is a
wired module — the same "ships a manifest or a mounted router" signal `canonical_module_shape`
uses — must have at least one test file the project attributes to it.

**Two layouts satisfy it, and the asymmetry between them is the decision.**

- `tests/<module>/test_*.py` is **canonical**: it is what `terp scaffold` now emits and what
  `terp guide testing` teaches. A module accumulates test files, and a directory holds them
  without anyone inventing a naming convention to keep them apart.
- `tests/test_<module>_*.py` is **recognised**, not taught.

Recognising the second is the part that deserves the argument, because ADR 0103's instinct
is to pick one pattern. The test ADR 0111 sets is legibility, not uniformity, and both
layouts are equally legible to a tool — each states "these tests belong to that module" in a
way a check can read without guessing. What refusing the flat form would buy is uniformity;
what it would cost is concrete. An application whose modules are, in fact, tested would fail
the gate, and its only way through would be
`# arch-allow-modules-ship-tests: <reason>` — a marker that says *this module has no tests*
about a module that has them. **A gate satisfiable only by a false statement is worse than a
gate that accepts the same true claim written two ways**, and it corrupts the escape-hatch
budget as well, which is supposed to measure real debt.

There is a second, quieter reason, and this platform has paid for it recently enough to
recognise the shape: a rule that names a destination the reference implementation does not
provide is a rule that gets worked around rather than followed. Had the directory been
mandated alone, the Standard would have required, on the day it shipped, a layout the
platform's own example did not use.

**Tests live in the project's `tests/` tree, not inside the module directory.** That is where
this repository keeps its own, and it is where a test that drives the composed app has to
live — the fixtures build the whole application. Putting a `tests/` inside every module would
have made the rule trivially checkable and the tests harder to write, which is the wrong
trade. The rule reaches `app_root.parent / "tests"` to find them, the same reach
`_coverage_is_strict` already makes for the control plane; an in-root `app/tests/` is accepted
too, because the Standard's corpus copies one tree into the scanned root and cannot create a
true sibling of it.

**The scaffold now writes the module's test package** — `tests/<name>/__init__.py` and a
`test_<name>_module.py` that asserts the manifest declares the module and its data layer, and
that writing requires more authority than reading. Two real assertions, no database, and they
pass on generation: a module the platform hands out is born conformant instead of owing a debt
nobody mentioned.

**Adoption needs no new mechanism.** A module that genuinely has no tests takes the escape
marker, which spends the application's escape-hatch budget — already a shrink-only ratchet.
The debt is counted, visible, and cannot grow silently, which is exactly the posture a grace
window would have been invented to provide.

**The rule asks only that tests exist and are attributable.** Whether they are any good is a
different question, already asked by `no_empty_tests` and by an application's own coverage
gate. Conflating the two would have produced a rule that is either unenforceable or wrong.

## Consequences

- The reference application passes unchanged. The blocker recorded against this work — four
  modules non-conformant on day one — was a consequence of mandating one layout, and it
  dissolves rather than being paid.
- A generated module is tested from its first commit, and the generated test is a real one
  that fails if the manifest stops declaring its services or its policy levels read and write.
- An application that has neither layout gets a finding naming both, and a budgeted escape if
  the answer really is "not yet".
- The rule cannot tell a thorough test from a token one. It is a floor, deliberately: the
  alternative designs all reduce to measuring coverage, which is the app's own gate's job and
  not something a source scan can do honestly.
- A module named as a prefix of another (`note` beside `notes`) is not credited with its
  sibling's flat test file; the separator is required. Without that, one module answers for
  another and ships untested behind a green gate — the failure this rule exists to stop,
  reintroduced by the check itself.
- **The frontend half is not addressed here.** The surface has fifteen rules and none about
  tests, which is a real gap, but its rules are ESLint rules and ESLint cannot assert that a
  file is *absent* — the mechanism this rule uses does not exist there. That is a different
  decision with a different implementation, and it is deferred rather than declined. The
  trigger: when the frontend gains any project-level check that runs outside the linter, this
  rule's twin belongs in it.

## Alternatives considered and not taken

**Mandate the per-module directory only.** The uniform answer, and the one the backlog entry
assumed. It costs a forced migration for every existing application, and — until they migrate
— an escape marker whose text is false. The Standard would also have required, on the day it
shipped, a layout the reference application did not use.

**Mandate the flat file only.** Matches this repository's example, and scales badly: the
moment a module has three test files the naming convention is doing a directory's job.

**Put `tests/` inside the module directory.** It would make the canonical shape literally
carry its tests and the check trivial. But the platform's own tests are not organised that
way, an integration test over the composed app has no natural home inside one module, and the
rule would then require of applications something the reference implementation does not do.

**Require tests as a sixth entry in `canonical_module_shape`.** Tempting, since the entry's
title says tests belong to the shape. It would have made the existing rule's message ("a
module dir must carry models/schemas/service/router/module") false, since the sixth part is
not in the module dir at all, and it would have coupled a layout decision to a rule that is
purely about the module package. A separate rule can be escaped, budgeted and reasoned about
on its own terms.

**Add a grace window for adoption.** Considered and unnecessary. The escape-hatch budget is
already a shrink-only ratchet, so "not yet" is expressible, counted, and unable to grow — a
window would be a second mechanism saying the same thing with an expiry date nobody would
remember to enforce.
