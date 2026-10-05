# Declared business rules, and the tests held to them — design notes and the sequenced plan

> **Decision:** not yet recorded. This is a proposal. When phase 0's evidence is in and the design
> is accepted, it becomes an ADR and this file becomes its execution tracker.
>
> **Status:** proposed; nothing is built. **Audience:** platform/core team + agents.
>
> **Builds on:** [ADR 0009](../../decisions/0009-authoring-model-and-opinionation-boundary.md),
> [ADR 0015](../../decisions/0015-runtime-write-guarded-session.md),
> [ADR 0111](../../decisions/0111-flexibility-is-bounded-by-legibility-not-by-capability.md),
> [ADR 0122](../../decisions/0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md),
> [ADR 0139](../../decisions/0139-who-can-reach-what-is-pinned-not-merely-reportable.md), and the
> spec's `test-adequacy` lane.

The goal, in one line: let an application declare its business rules beside the columns they
govern, enforce them where every write lands, show them to the person who owns them, and hold the
application's tests to them.

## 1. What Terp already has

- **A write chokepoint that cannot be bypassed.** Traits are declared once on the model and
  honoured by `BaseService._save` (ADRs 0010 and 0012). ADR 0015 makes `_save` the only way a
  write-guarded session persists anything, and requests and jobs both run one. A rule honoured
  there holds for every write an application makes outside a migration.
- **An inspectable data model.** `terp inspect schema` projects the metadata as JSON so that
  external tooling can visualise the data model, and a workbench already draws it.
- **Pinning as a review mechanism.** ADR 0139 turns who-can-reach-what into a committed
  `authz-surface.json`, so a change to it is a diff a reviewer has to accept.
- **A home for declaration vocabularies.** ADR 0111 §5 puts them in terp-spec, so a workbench and
  a framework on different versions agree on what an application said about itself.
- **A test-adequacy lane with nothing behind it.** The spec names `test-adequacy` (recommended,
  reference realisation: diff-scoped mutation testing). `verify.py` emits it as `not-run`.
- **Coverage where it matters most.** The framework holds its own code to 100% of lines
  (`fail_under = 100`, ADR 0003). A generated application has no coverage bar; ADR 0119 asks only
  that every module has tests.

## 2. What is missing

ADR 0009 keeps business logic in code, on purpose. That leaves the largest surface of an
application invisible to every tool:

- which states an order may move between, and who may move it;
- what a row must always satisfy: a discount ceiling, an end date after a start date;
- what a stored figure is computed from: a margin, a VAT amount.

`terp inspect schema` can say that `quotes.discount_pct` is a numeric column. It cannot say that
it may not exceed 25. The gate that pins authority stays green while an agent turn moves the
ceiling to 30, because nothing knew there was a ceiling.

Three facts make that urgent:

1. **Rules stated in natural language are where agents are least reliable.** On 95 production
   decision models behind a national permit portal, models an LLM generated from the legal text
   agreed with the gold models on 51–53% of test scenarios on average. Giving the model
   input/output examples was the largest single improvement, +37% to +54% relative
   ([arXiv 2604.17153](https://arxiv.org/abs/2604.17153), April 2026).
2. **The person who owns a rule cannot read the code it lives in** (ADR 0103's design centre).
   They can confirm "a discount above 25% is refused". They cannot confirm a branch in
   `QuoteService.update`.
3. **Neither coverage nor mutation can tell what the owner meant.** An agent that misreads a rule
   writes the code and the tests from the same misreading: every line runs and every mutant dies.

## 3. The design: declared rules

### 3.1 Three kinds of rule, and nothing else

A table may declare rules of exactly three kinds, on the model, next to the columns they read
(the *which*, ADR 0011):

| Kind | What it says | Example |
|---|---|---|
| `Transitions` | the moves a status column may make, and the permission each move needs | `draft → approved` needs `quotes.approve` |
| `Invariant` | a condition every write of the row satisfies, over that row's own columns | `discount_pct <= 25`; `ends_on >= starts_on` |
| `Derived` | a column computed from that row's own columns | `margin = revenue − material_cost − labour_cost` |

Each rule carries a stable id (`quote.discount-ceiling`), one sentence for the owner, and
optionally a `source` naming the document it comes from ("Pricing policy 2026, §4.2"). The
sentence is what a refusal says and what a workbench shows. It is the English fallback: a
frontend dispatches on the rule id like any other error code, so a translated sentence lives where
the application's other copy lives (ADR 0105). The platform never interprets the source.

Everything else stays code: totals over child rows, rules over time, lookups, anything that needs
a loop. Aggregates over a declared reference may come later, with their own evidence, because
they bring concurrency with them: a child's write changes the parent's figure under optimistic
concurrency control.

### 3.2 A rule is data, not a function

An expression is built from column references, literals, `+ − × ÷`, comparisons,
`and`/`or`/`not`, `min`/`max` and an explicit `round(…, places)`. There are no Python callables,
no function calls and no loops.

A callable would be simpler to write and would cost every property this design exists for:
`inspect` could not serialise it, a workbench could not render it, a checker could not find a
contradiction in it, and §4.4 could not mutate it. The closed grammar is also what keeps this on
the right side of ADR 0009: it cannot grow into a language, because there is no way to write a
loop in it. The way out of it is code, not a bigger grammar.

An illustrative shape, not a fixed API:

```python
class Quote(BaseTable, table=True):
    status: str = Field(default="draft", max_length=20)
    revenue: Decimal
    material_cost: Decimal
    labour_cost: Decimal
    discount_pct: Decimal
    margin: Decimal = Field(default=Decimal(0))

    rules: ClassVar[Rules] = Rules(
        Transitions(
            "quote.flow", column="status", initial="draft",
            moves={("draft", "approved"): APPROVE,
                   ("approved", "ordered"): PLACE,
                   ("approved", "draft"): APPROVE},
            says="A quote is approved before it is ordered.",
        ),
        Invariant(
            "quote.discount-ceiling", col("discount_pct") <= 25,
            says="A discount above 25% is refused.",
        ),
        Derived(
            "quote.margin", "margin",
            col("revenue") - col("material_cost") - col("labour_cost"),
            says="The margin is the revenue minus material and labour cost.",
        ),
    )
```

### 3.3 Enforced where every write lands, in Python

`BaseService._save` evaluates a table's rules inside the write transaction, before the flush:

- a `Derived` column is computed and assigned by the framework, and a value the caller supplied is
  never used;
- an `Invariant` that is false refuses the write;
- a `Transitions` column compares the row's previous value with the new one. A move that is not
  declared refuses the write. A declared move the principal lacks the permission for is the
  existing authorization refusal. A new row starts in `initial` or is refused.

A refusal is the existing `ValidationFailedError` envelope with one `ErrorDetail` per broken rule:
`code` is the rule id, `loc` the column, `msg` the owner sentence. No exception text reaches the
client.

The rules are evaluated in Python with `Decimal`, never in SQL. The two verified dialects do
arithmetic differently: SQLite, the development and test engine (ADR 0069), does decimal
arithmetic in binary floating point, and PostgreSQL does it exactly. A formula the database
computed would give two answers; one evaluator gives one. So there are no generated columns,
`CHECK` constraints or triggers here. A `CHECK` backstop for a condition both dialects evaluate
identically can come later. Keeping rules out of the DDL also keeps a changed formula from becoming
a schema migration, and keeps a refusal an owner sentence rather than an `IntegrityError`.

The declaration is validated at boot, fail closed. A rule that names a column the table does not
have, compares a string with a number, or requires a permission the module does not declare
refuses to start the application. What can be decided cheaply beyond that is reported by verify:
a state no move reaches, a derived column that reads itself, two bounds on one column that exclude
each other.

A data migration writes through the maintenance engine, not `_save`, by design. One that writes a
ruled column has to leave every row satisfying its rules, and the migration's review is where that
is checked.

### 3.4 Readable through inspect, and pinned like who-can-reach-what

`terp inspect schema` gains, per table, a `rules` list: id, kind, the columns read and written,
the expression as a tree, the owner sentence, the source, and a content hash. The hash is the
rule's version. The audit record of a write carries the hashes of the rules that decided it, and
the log line of a refusal carries the hash of the rule that refused it, so "which rule did this"
still has an answer after the rule has changed.

The rules of every table are also rendered as a committed `rules-surface.json`, and a verify check
diffs the composed rules against it, exactly as ADR 0139 does for `authz-surface.json`. A ceiling
moved from 25 to 30, a transition added, a formula changed: each fails the gate until the surface
is re-pinned in the same change, which puts the change in front of whoever reviews it. The gate
does not judge whether 30 is right. It makes sure someone saw that it changed.

The permission a move names has to be one the module already declares. Who holds it stays in
`authz-surface.json`, which move needs it is in `rules-surface.json`, and both are pinned.

### 3.5 The vocabulary lives in the spec

The JSON shape `inspect` emits and the surface pins is a declaration vocabulary read by two
programs, so it is published in terp-spec as `rules-declaration.schema.json` and versioned with
the spec. The framework keeps the enforcement; the spec keeps the words. A reader that meets a
kind it does not know reports it and carries on, per ADR 0111's degradation test.

### 3.6 A legibility contract, not conformance

Declaring rules is optional. An application that declares none passes every gate exactly as it
does today; its rules are code, and a workbench says plainly that it cannot show them. The
platform never decides whether a rule is right. It enforces truth about the application's own
statement (ADR 0111 §1): a declared rule is enforced, pinned and shown.

Read against ADR 0006's quadruple:

- the typed declaration with a safe default is `Rules`, whose absence changes nothing;
- the fail-closed runtime half is §3.3, at the write and at boot;
- the escape is not to declare, which leaves the logic in code where it is today;
- the build-time half is `no_manual_derived_writes`: a module that assigns a `Derived` column by
  hand contradicts its own declaration. Under ADR 0122 it is not added on analogy with
  `no_manual_actor_stamping`. It lands when the benchmark or a real application shows an agent
  doing it. The data is protected either way, because `_save` overwrites the column.

### 3.7 What a workbench does with it

The fields arrive with their reader (ADR 0122 §3). A workbench such as Terp Studio:

- draws the rules on its data-model view: the formula on a derived column, the owner sentence
  beside a guarded column, a state diagram for a transitions column;
- shows a re-pinned `rules-surface.json` as plain-language changes for the owner to approve ("the
  discount ceiling changes from 25% to 30%");
- shows a refusal as its owner sentence, not its rule id;
- turns a surviving rule mutant (§4.4) into a question for the owner.

## 4. The design: testing strategy

### 4.1 Why not 100% coverage and 100% mutation everywhere

It is the tempting bar, and the reasons against it get stronger, not weaker, when an agent writes
the tests:

1. **Some mutants cannot be killed.** A mutant that does not change behaviour (an equivalent
   mutant) survives every test, and deciding equivalence is undecidable in general. A 100% bar
   therefore needs an exemption, and for an agent the exemption is the cheapest way to green.
2. **A metric an agent is held to is the metric it optimises.** The cheapest way to kill mutants
   is to snapshot outputs or assert on implementation detail. That pins today's behaviour, right
   or wrong, and turns every refactor into a test rewrite.
3. **Mutation measures sensitivity, not intent.** A suite that kills every mutant of a misread
   rule defends the misreading.
4. **Cost scales with the whole codebase.** Mutants times test time, on every change, turns a
   suite of minutes into hours.
5. **100% coverage of application code buys assertion-free tests of glue.** `no_empty_tests`
   refuses the syntactic form. The semantic form, a test that runs a line and checks nothing about
   it, passes.

### 4.2 Prevention first

A property the platform enforces by construction is tested in the framework, once: the guard,
tenancy, ownership, references, the audited write. Applications are not asked to re-test them.
The framework keeps its 100% line bar because it is the substrate every application trusts. An
application's tests are for what is the application's own, and most sharply for its declared
rules.

### 4.3 Examples are the oracle

Each declared rule comes with examples: concrete cases with an expected outcome, written as
ordinary tests in the module's test tree (ADR 0119).

- "A manager gives 25%: accepted. 26%: refused."
- "An approved quote moves to ordered with `quotes.place`. A draft quote does not."
- "Revenue 1000, material 400, labour 250: margin 350."

Examples are the oracle because they are not derived from the declaration. An owner can confirm an
example without reading an expression, and an example that disagrees with its rule means one of
the two is wrong, which is exactly the finding. Examples also help the agent: input/output examples
were the largest single improvement in the decision-model study (§2).

### 4.4 Rule mutation: blocking, at 100%

For every declared rule the toolchain derives a small, fixed set of mutants from the declaration:

- each comparison boundary moved (`<=` to `<`, `25` to `24` and to `26`);
- each arithmetic operator swapped, and each `round` place count moved by one;
- each declared move removed, one undeclared move added, and each required permission dropped.

The rule is data, so no source is rewritten. A baseline run records which tests evaluated which
rule. Each mutant is then loaded in place of its rule through the framework's existing pytest
plugin, and only those tests run, in-process, stopping at the first failure. Each mutant must make
at least one test fail.

100% is the right bar here, and only here:

- **The mutants are few.** A handful per rule, each re-running a handful of tests: seconds to a
  minute, not hours.
- **They are generated so as not to be equivalent.** On an integer column, `<= 25` and `< 26` are
  the same rule, and the generator emits only one of them.
- **A survivor means one of two things, and both are worth knowing.** Either no example sits on
  that boundary, or another rule already decides every case this one would, which makes this one
  redundant.

A survivor is reported as the missing example, in the owner's language: "Nothing says what happens
at exactly 25%", or "no example has a labour cost, so a formula that adds it instead of
subtracting it would pass". The fix is an example, never an exemption. A redundant rule is removed
or merged.

### 4.5 Hand-written code: no new survivor per change

For the code an application writes by hand, mutation runs over the lines a change touches, with
tests selected by which ones cover the mutated line. mutmut (Python) and Stryker (TypeScript) are
the reference realisation. It runs in the `full` and `release` profiles, never after every agent
turn.

The bar is a ratchet, not a percentage: **a change may not add a surviving mutant.** A survivor is
either killed by a test or marked equivalent with the tool's own suppression comment carrying a
reason, counted in the module's escape-hatch budget like an `arch-allow` marker (ADR 0103:
escapable by proof, never quietly). Survivors on lines the change did not touch are not its debt.
A score over the whole codebase was rejected, because a new survivor hides behind old kills.

The framework's own code takes the same per-change ratchet, plus a periodic full run whose score
may only rise.

### 4.6 Coverage: a report and a floor, never a target

The framework keeps `fail_under = 100`. An application gets no coverage percentage to reach. It
may adopt a floor that only rises, as a ratchet against decay, but coverage is never offered as
evidence of adequacy; the spec already says it is not.

### 4.7 The lane

This realises the `test-adequacy` lane: its composing checks become `rule-mutation` and
`diff-mutation`. The lane stays *recommended*, because ADR 0122 §4 fixes requirement levels and a
release claim should not start depending on a check with no run history. Inside an application
that declares rules, `rule-mutation` is blocking in that application's own gate regardless: the
application declared the rules, and holding its tests to its own declaration is truth about itself
(ADR 0111), not a conformance bar.

## 5. The plan, in phases that each end somewhere shippable

Phases 0 and 1 are independent and can run side by side. Phase 2 waits for phase 0's result.

### Phase 0 — evidence

- [ ] Add a business-rules task to the agent-success benchmark: one module with a status flow, a
      discount ceiling and a margin, built by an agent in service code from a plain-language
      prompt.
- [ ] Count defects against owner-written examples: a boundary off by one, a rule enforced on
      create but not on update, a skipped state, a figure computed from the wrong columns.
- [ ] Record the baseline. It is the evidence ADR 0122 asks for, and the number phase 2 has to
      move.

### Phase 1 — mutation on changed code

- [ ] Diff-scoped mutation for Python (mutmut) and TypeScript (Stryker): changed lines only, tests
      selected by coverage of the mutated line, results cached by content hash.
- [ ] The equivalent-mutant suppression counted in the escape-hatch budget.
- [ ] `diff-mutation` composes the `test-adequacy` lane in `full` and `release`; measure run times
      on the framework and on `apps/example`.
- [ ] A periodic full run of the framework, its score ratcheted.

### Phase 2 — declared rules, core

- [ ] terp-spec: `rules-declaration.schema.json`, released first (the coupled-CI order).
- [ ] terp-core: `Rules`, `Transitions`, `Invariant`, `Derived`, `col`; evaluation at `_save`;
      refusals in the `ValidationFailedError` envelope; boot validation.
- [ ] terp-cli: the `inspect schema` projection, `rules-surface.json`, and a verify check that
      diffs it.
- [ ] `apps/example`: one table declaring a flow, two invariants and a derived column, with
      examples.
- [ ] A `terp guide` topic and a template `AGENTS.md` line, so an agent reaches for a declaration
      before a service branch.
- [ ] Re-run the phase 0 task with the declared variant; the delta is the claim.

### Phase 3 — rule mutation and examples

- [ ] A mutant generator per kind, normalising known equivalents.
- [ ] The baseline map from rules to the tests that evaluate them, and the pytest-plugin swap.
- [ ] Survivors reported as missing examples or redundant rules.
- [ ] `rule-mutation` composes the lane, and blocks in an application that declares rules.

### Phase 4 — the workbench (lands in terp-studio)

- [ ] Rules on the data-model view: formula, owner sentence, state diagram.
- [ ] A re-pinned `rules-surface.json` shown as plain-language changes for the owner to approve.
- [ ] Refusals shown as their owner sentence; surviving rule mutants shown as questions.

## 6. Decisions to record

- When phase 0's evidence is in: an ADR for declared rules (the three kinds, the enforcement point,
  pinning, the spec vocabulary).
- With phase 1: an ADR for how test adequacy is realised (rule mutation at 100%, the per-change
  ratchet, coverage as a floor).
- Whether `no_manual_derived_writes` enters the catalog, on ADR 0122 evidence only.
- A spec release for `rules-declaration.schema.json`; later, on run-time evidence, whether
  `test-adequacy` becomes required.

## 7. Deliberately not in scope

- **A rules engine or a DMN runtime.** A second runtime, opaque to the agent that has to debug it,
  and ADR 0009's Target B with a standard behind it.
- **Rules enforced by the database** (generated columns, `CHECK`, triggers). Different arithmetic
  on the two verified dialects, a migration per formula change, and refusals no owner can read.
- **Rules as Python callables.** Not inspectable, renderable, analysable or mutable.
- **Rules as rows the owner edits at runtime.** That would be the one path in the platform that
  changes behaviour without a diff. An owner who wants a different ceiling asks for it, and the
  change arrives pinned.
- **Tests generated from the declaration as the oracle.** They agree with the declaration by
  construction, so they only test the evaluator, which the framework tests once.
- **100% coverage and a 100% mutation score everywhere** (§4.1), and **a mutation-score percentage
  per application** (§4.5).
- **LLM-written mutants in the gate.** Not reproducible; possible later as advisory findings.
- **Cross-row aggregates and rules over time**, until evidence asks for them.

## 8. Open questions

- The API shape: a `ClassVar` on the model, or a declaration beside the `ModuleSpec`.
- The `Decimal` rounding default, and where a place count is declared.
- How existing rows are recomputed when a formula changes: a data-migration template, or a
  framework command.
- Who confirms examples, and how a workbench phrases a surviving mutant as a question.
- The run-time budget for `diff-mutation` in `full`, and whether rule mutation is cheap enough for
  `quick`.
- For aggregates later: what evidence justifies them, and how an OCC conflict on the parent row is
  handled.
