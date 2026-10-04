# 0173 — Tests must notice a changed rule, and a change may not add a surviving mutant

- **Status:** Proposed, together with
  [ADR 0172](0172-a-business-rule-is-declared-beside-its-columns-enforced-at-the-write-and-pinned.md).
  Nothing here is built: the toolchain still emits the `test-adequacy` lane as `not-run`
  (`packages/backend/cli/src/terp/cli/verify.py`).
- **Date:** 2026-10-04
- **Relates:** [ADR 0003](0003-conformance-and-coverage-gate.md) (the framework's 100% line
  bar), [ADR 0119](0119-a-module-owes-tests-and-the-standard-recognises-two-places-to-keep-them.md)
  (a module owes tests), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md)
  (escapable by proof: the route for an equivalent mutant),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (holding an
  application to its own declaration is truth about itself),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (§4: the
  lane's requirement level stays fixed), the spec README's `test-adequacy` lane

---

## Context

Three different things get called "testing", and they answer different questions.

- **Coverage** says which lines ran. The framework holds its own code to 100% of lines
  (`fail_under = 100`, ADR 0003). A generated application carries no coverage bar; ADR 0119 asks
  only that every module has tests.
- **Adequacy** asks whether the suite could have failed. The spec names it as the
  `test-adequacy` assurance lane, recommended, with diff-scoped mutation testing as its
  reference realisation, and says that "coverage does not evidence this lane". The toolchain
  emits it as `not-run`, because a mutation run is "minutes of CPU per change rather than
  seconds and is a decision about the merge bar" (`verify.py`).
- **Correctness** asks whether the application does what its owner meant. Neither of the first
  two can answer that. An agent that misreads a rule writes the code and the tests from the same
  misreading: every line runs and every mutant dies.

The tempting bar is 100% coverage and a 100% mutation score everywhere. It is rejected here,
for reasons that get stronger, not weaker, when an agent writes the tests:

1. **Some mutants cannot be killed.** A mutant that does not change behaviour (an equivalent
   mutant) survives every test, and deciding equivalence is undecidable in general. A 100% bar
   therefore needs an exemption, and for an agent the exemption is the cheapest way to green.
2. **A metric an agent is held to is the metric it optimises.** The cheapest way to kill
   mutants is to snapshot outputs or assert on implementation detail. That pins today's
   behaviour, right or wrong, and turns every refactor into a test rewrite.
3. **Mutation measures sensitivity, not intent.** A suite that kills every mutant of a misread
   rule defends the misreading.
4. **Cost scales with the whole codebase.** Mutants times test time, on every change, turns a
   suite of minutes into hours.
5. **100% coverage of application code buys assertion-free tests of glue.** `no_empty_tests`
   refuses the syntactic form. The semantic form, a test that runs a line and checks nothing
   about it, passes.

The platform's answer to what must be true of every application is already prevention, not
testing. The guard, tenancy, ownership, references and the audited write are enforced by
construction and tested once, in the framework. An application's tests are for what is the
application's own.

## Decision

### 1. Prevention first: what the framework enforces is tested in the framework

A property the platform enforces by construction is not re-tested per application. The
framework's 100% line bar stays, because the framework is the substrate every application
trusts. The per-application question narrows to the application's own behaviour, and most
sharply to the rules it declares.

### 2. A declared rule is pinned by examples, and the examples are the oracle

Each rule declared under ADR 0172 comes with examples: concrete cases with an expected outcome,
written as ordinary tests in the module's test tree (ADR 0119).

- "A manager gives 25%: accepted. 26%: refused."
- "An approved quote moves to ordered with `quotes.place`. A draft quote does not."
- "Revenue 1000, material 400, labour 250: margin 350."

Examples are the oracle because they are not derived from the declaration. An owner can confirm
an example without reading an expression, and an example that disagrees with its rule means one
of the two is wrong, which is exactly the finding. Examples help the agent too: in the
decision-model study ADR 0172 cites, input/output examples were the largest single improvement
(+37% to +54% relative) in what the model generated.

### 3. Rule mutation is blocking, and its bar is 100%

For every declared rule, the toolchain derives a small, fixed set of mutants from the
declaration itself:

- each comparison boundary moved (`<=` to `<`, `25` to `24` and to `26`);
- each arithmetic operator swapped, and each `round` place count moved by one;
- each declared move removed, one undeclared move added, and each required permission dropped.

The rule is data, so no source is rewritten. A baseline run records which tests evaluated which
rule. Each mutant is then loaded in place of its rule through the framework's existing pytest
plugin, and only those tests run, in-process, stopping at the first failure. Each mutant must
make at least one test fail.

A 100% bar is right here, and only here:

- **The mutants are few.** There are a handful per rule, each re-running a handful of tests, so
  the step takes seconds to a minute, not hours.
- **They are generated so as not to be equivalent.** On an integer column, `<= 25` and `< 26`
  are the same rule, and the generator emits only one of them.
- **A survivor means one of two things, and both are worth knowing.** Either no example sits on
  that boundary, or another rule already decides every case this one would, which makes this
  one redundant.

A survivor is reported as the missing example, in the owner's language: "Nothing says what
happens at exactly 25%", or "no example has a labour cost, so a formula that adds it instead of
subtracting it would pass". The fix is an example, never an exemption. A redundant rule is
removed or merged.

Rule mutation runs in the `full` and `release` profiles. A workbench may also run it after a
turn that re-pinned `rules-surface.json`, since that is exactly when a rule changed.

### 4. Hand-written code: no new survivor on the diff

For the code an application writes by hand, mutation runs over the lines a change touches:
diff-scoped, with tests selected by which ones cover the mutated line. mutmut (Python) and
Stryker (TypeScript) are the reference realisation. It runs in the `full` and `release`
profiles, never after every agent turn.

The bar is a ratchet, not a percentage: **a change may not add a surviving mutant.** A survivor
is either killed by a test or marked equivalent with the tool's own suppression comment carrying
a reason, counted in the module's escape-hatch budget like an `arch-allow` marker (ADR 0103:
escapable by proof, never quietly). Survivors on lines the change did not touch are not its
debt.

The framework's own code takes the same per-change ratchet, plus a periodic full run whose score
may only rise.

### 5. Coverage stays a report and a floor, never a target

The framework keeps `fail_under = 100`. An application gets no coverage percentage to reach. It
may adopt a floor that only rises, as a ratchet against decay, but coverage is never offered as
evidence of adequacy; the spec already says it is not.

### 6. The lane, and what it claims

This realises the `test-adequacy` lane: its composing checks become `rule-mutation` and
`diff-mutation`. The lane stays *recommended*. ADR 0122 §4 fixes requirement levels, and a
release claim should not start depending on a check with no run history. Promoting the lane is a
spec decision for later, on evidence of run times and false findings.

Inside an application that declares rules, `rule-mutation` is blocking in that application's
own gate regardless. The application declared the rules, and holding its tests to its own
declaration is truth about itself (ADR 0111), not a conformance bar.

## Consequences

- An application that declares no rules sees one new check, `diff-mutation`, in `full` and
  `release`, and nothing new in `quick`.
- An application that declares rules writes examples for them. That is the cost, and it is also
  the confirmation an owner can give without reading code.
- The equivalent-mutant marker joins the escape-hatch budget, so its count is visible and
  ratcheted like every other escape.
- The rule-mutation harness rides the existing pytest plugin, so a module's tests need no new
  fixtures to be run against a mutant.
- Run time is a budget the profile owns. If `diff-mutation` routinely exceeds it, the answer is
  narrower selection, not a lower bar.

## Alternatives considered and not taken

- **100% coverage and a 100% mutation score everywhere.** See the five points in the context.
- **A mutation-score percentage per application.** A new survivor hides behind old kills; the
  per-change ratchet (§4) is stricter where the risk is, and cheaper.
- **Tests generated from the declared rules.** They agree with the rules by construction, so
  they would test the evaluator, which the framework already tests once.
- **LLM-written mutants.** More realistic faults, but not reproducible, and a gate needs the
  same verdict on the same commit. Possible later as advisory findings.
- **Mutating everything nightly instead of per change.** It finds a survivor after the change
  that introduced it has merged and its context is gone.
