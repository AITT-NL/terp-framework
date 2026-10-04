# 0172 — A business rule is declared beside its columns, enforced at the write, and pinned

- **Status:** Proposed. Nothing here is built. Acceptance waits on the evidence named in §8,
  which also sizes the first slice.
- **Date:** 2026-10-04
- **Relates:** [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (the low-code line
  this stays behind), [ADR 0011](0011-model-traits-vs-control-plane-policy.md) (the *which* lives
  on the model), [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md) and
  [ADR 0012](0012-actor-stamping-trait.md) (traits honoured at the write chokepoint),
  [ADR 0015](0015-runtime-write-guarded-session.md) (why that chokepoint is the only way in),
  [ADR 0069](0069-verified-database-dialects-and-schema-direction.md) (why the arithmetic is not
  done in SQL), [ADR 0072](0072-database-additivity-review.md) (status columns are plain strings),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (a legibility
  contract, and where its vocabulary lives),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (the bar a new
  rule has to clear), [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md)
  (pinning as the review mechanism),
  [ADR 0173](0173-tests-must-notice-a-changed-rule-and-a-change-may-not-add-a-surviving-mutant.md)
  (how the tests are held to what is declared here)

---

## Context

Terp enforces the cross-cutting half of an application and leaves the rest to code. ADR 0009
drew that line on purpose: "genuine business logic stays as code", because the alternative,
modules as fill-in forms, "moves bugs into an opaque DSL that agents and humans cannot debug".

The line holds. What it leaves out is now the largest surface in an application that no tool
can see:

- which states an order may move between, and who may move it;
- what a row must always satisfy: a discount ceiling, an end date after a start date;
- what a stored figure is computed from: a margin, a VAT amount.

An agent writes these into service code. `terp inspect schema` can say that
`quotes.discount_pct` is a numeric column; it cannot say that it may not exceed 25. The gate
that pins who may reach which route (ADR 0139) stays green while an agent turn moves the ceiling
to 30, because nothing knew there was a ceiling.

Two observations make that more than an inconvenience.

**Rules stated in natural language are where agents are least reliable.** On 95 production
decision models behind a national permit portal, models an LLM generated from the legal text
agreed with the gold models on 51–53% of test scenarios on average, and giving the model
input/output examples was the largest single improvement
([arXiv 2604.17153](https://arxiv.org/abs/2604.17153), April 2026). An agent writing a rule into
a service method is the same exercise, with no gold model to compare against.

**The person who owns the rule cannot read the code it lives in.** ADR 0103 puts that person at
the design centre. They can confirm "a discount above 25% is refused". They cannot confirm a
branch in `QuoteService.update`.

What the platform already has makes a narrow answer cheap:

- Traits are declared once on the model and honoured by `BaseService._save` (ADRs 0010 and
  0012), and ADR 0015 makes `_save` the only way a write-guarded session persists anything.
  Requests and jobs both run one, so a rule honoured there holds for every write the application
  makes outside a migration.
- `terp inspect schema` already projects the metadata as JSON "so external tooling can visualize
  the data model", and a workbench already draws it.
- ADR 0139 already turns an authority claim into a committed artifact whose change is a diff a
  reviewer has to accept.

## Decision

### 1. Three kinds of rule, and nothing else

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
frontend dispatches on the rule id like any other error code, so a translated sentence lives
where the application's other copy lives (ADR 0105). The source is text the platform never
interprets.

Everything else stays code, as ADR 0009 requires: totals over child rows, rules over time,
lookups, anything that needs a loop. A later ADR may add aggregates over a declared reference. It
would need its own evidence, because it brings concurrency with it: a child's write changes the
parent's figure under optimistic concurrency control.

### 2. A rule is data, not a function

An expression is built from column references, literals, `+ − × ÷`, comparisons,
`and`/`or`/`not`, `min`/`max` and an explicit `round(…, places)`. There are no Python callables,
no function calls and no loops.

A callable would be simpler to write and would cost every property this ADR exists for:
`inspect` could not serialise it, a workbench could not render it, a checker could not find a
contradiction in it, and ADR 0173 could not mutate it. The closed grammar is also what keeps the
vocabulary on the right side of ADR 0009. It cannot grow into a language, because there is no
way to write a loop in it, and the way out of it is code, not a bigger grammar.

An illustrative shape; this ADR does not fix the API:

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

### 3. Enforced where every write lands, in Python

`BaseService._save` evaluates a table's rules inside the write transaction, before the flush:

- a `Derived` column is computed and assigned by the framework, and a value the caller supplied
  is never used;
- an `Invariant` that is false refuses the write;
- a `Transitions` column compares the row's previous value with the new one. A move that is not
  declared refuses the write. A declared move the principal lacks the permission for is the
  existing authorization refusal. A new row starts in `initial` or is refused.

A refusal is the existing `ValidationFailedError` envelope with one `ErrorDetail` per broken
rule: `code` is the rule id, `loc` the column, `msg` the owner sentence. No exception text
reaches the client.

The rules are evaluated in Python with `Decimal`, never in SQL. The two verified dialects do
arithmetic differently: SQLite, the development and test engine (ADR 0069), does decimal
arithmetic in binary floating point, and PostgreSQL does it exactly. A formula the database
computed would give two answers; one evaluator gives one. For the same reason this ADR adds no
generated columns, `CHECK` constraints or triggers. A later ADR may add a `CHECK` backstop for a
condition both dialects evaluate identically. Keeping the rules out of the DDL also keeps a
changed formula from becoming a schema migration, and keeps a refusal an owner sentence rather
than an `IntegrityError`.

The declaration is validated at boot, fail closed, like every other registry. A rule that names
a column the table does not have, compares a string with a number, or requires a permission the
module does not declare refuses to start the application. What can be decided cheaply beyond
that is reported by verify rather than refused at boot: a state no move reaches, a derived column
that reads itself, two bounds on one column that exclude each other.

### 4. Readable through inspect, and pinned like who-can-reach-what

`terp inspect schema` gains, per table, a `rules` list: id, kind, the columns read and written,
the expression as a tree, the owner sentence, the source, and a content hash. The hash is the
rule's version. The audit record of a write carries the hashes of the rules that decided it,
and the log line of a refusal carries the hash of the rule that refused it, so "which rule did
this" still has an answer after the rule has changed.

The rules of every table are also rendered as a committed `rules-surface.json`, and a verify
check diffs the composed rules against it. That is the mechanism ADR 0139 built for
`authz-surface.json`, for the same reason. A ceiling moved from 25 to 30, a transition added, a
formula changed: each fails the gate until the surface is re-pinned in the same change, which
puts the change in front of whoever reviews it. The gate does not judge whether 30 is right. It
makes sure someone saw that it changed.

The permission a move names has to be one the module already declares. Who holds it stays in
`authz-surface.json`, which move needs it is in `rules-surface.json`, and both are pinned.

### 5. The vocabulary lives in the spec

The JSON shape `inspect` emits and the surface pins is a declaration vocabulary read by two
programs, so it is published in terp-spec as `rules-declaration.schema.json` (ADR 0111 §5) and
versioned with the spec. The framework keeps the enforcement; the spec keeps the words. A reader
that meets a kind it does not know reports it and carries on, per ADR 0111's degradation test,
so a newer framework never breaks an older workbench.

### 6. A legibility contract, not conformance

Declaring rules is optional. An application that declares none passes every gate exactly as it
does today; its rules are code, and a workbench says plainly that it cannot show them. The
platform never decides whether a rule is right. What it enforces is truth about the
application's own statement (ADR 0111 §1): a declared rule is enforced, pinned and shown.

Read against ADR 0006's quadruple: the typed declaration with a safe default is `Rules`, whose
absence changes nothing; the fail-closed runtime half is §3, at the write and at boot; the escape
is not to declare, which leaves the logic in code where it is today. The build-time half is the
one rule this implies, `no_manual_derived_writes`: a module that assigns a `Derived` column by
hand contradicts its own declaration, by analogy with `no_manual_actor_stamping`. Under
ADR 0122 it is not added on analogy. It lands when the benchmark in §8, or a real application,
shows an agent doing it. The data is protected either way, because `_save` overwrites the column.

### 7. What a workbench does with it

The fields arrive with their reader (ADR 0122 §3). A workbench such as Terp Studio:

- draws the rules on its data-model view: the formula on a derived column, the owner sentence
  beside a guarded column, a state diagram for a transitions column;
- shows a re-pinned `rules-surface.json` as plain-language changes for the owner to approve
  ("the discount ceiling changes from 25% to 30%");
- shows a refusal as its owner sentence, not its rule id.

### 8. What earns acceptance, and the first slice

Acceptance needs evidence, not analogy (ADR 0122 §2). The evidence is a benchmark in which an
agent implements the same three rules in the same module twice, once in service code and once
declared, and the defects in each are counted. That includes the defects an owner would only
catch by reading code.

The first slice is the smallest one that shows all of it end to end:

1. the three kinds, the `_save` evaluation and the boot validation in `terp-core`;
2. the `inspect schema` projection, `rules-surface.json` and its verify check in `terp-cli`;
3. `rules-declaration.schema.json` in terp-spec, released first, per the coupled-CI order;
4. one table in `apps/example` that declares one flow, two invariants and one derived column,
   with the examples ADR 0173 asks for.

## Consequences

- `terp.core` grows a public declaration surface (`Rules`, `Transitions`, `Invariant`,
  `Derived`, `col`), and `_save` grows one evaluation step. A table without rules pays nothing.
- A derived column is never written by a request. It drops out of the create and update
  schemas, the way `id` and the timestamps already do.
- Rows written before a `Derived` rule existed, or before its formula changed, disagree with it
  until they are rewritten. The change that adds or changes a formula ships the data migration
  that recomputes them; a formula change without one is a review finding, not silent drift.
- A data migration writes through the maintenance engine, not `_save`, by design. One that
  writes a ruled column has to leave every row satisfying its rules, and the migration's review
  is where that is checked.
- Rule changes become reviewable the way authority changes already are. That is the point, and
  it is also a cost: an application that changes its ceilings every week re-pins every week.
- The grammar will be asked to grow. Each request gets ADR 0009's answer: if it needs a loop, it
  is code.

## Alternatives considered and not taken

- **A rules engine or a DMN runtime.** A second runtime, opaque to the agent that has to debug
  it. The long-standing promise that business users will maintain the rules themselves has a
  poor record. It is ADR 0009's Target B with a standard behind it.
- **Rules enforced by the database** (generated columns, `CHECK`, triggers). Different arithmetic
  on the two verified dialects, a migration for every formula change, and refusals no owner can
  read. Kept open only as a backstop (§3).
- **Rules as Python callables.** Not inspectable, renderable, analysable or mutable (§2).
- **Rules as rows the owner edits at runtime.** A threshold changed in a settings screen skips
  the agent, the gate and the review, and becomes the one path in the platform that changes
  behaviour without a diff. An owner who wants a different ceiling asks for it, and the change
  arrives pinned.
- **Tests generated from the declaration.** They agree with the declaration by construction, so
  they can only test the framework's evaluator, which the framework's own suite tests once. The
  independent check is examples (ADR 0173).
