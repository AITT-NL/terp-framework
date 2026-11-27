# Declared business rules, and the tests held to them — design notes and the sequenced plan

> The declared-rules design is awaiting an ADR. This document also tracks implementation.
>
> The pytest write observer and quote persistence checks have been prototyped locally.
>
> The [backend adoption proposal](backend-adoption-and-custom-code.md) describes how teams can
> mix these rules with custom Python and choose which decisions an owner reviews.
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

- **A guarded service write path.** Creates, updates and soft deletes use
  `BaseService._save`. Hard deletes use `_remove`. Nested service writes share a transaction.
  The proposed rules use these service operations and the transaction boundary (§3.3).
  [Service implementation](../../../packages/backend/core/src/terp/core/base_service.py)

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

`terp inspect schema` identifies `quotes.discount_pct` as a numeric column. A change to the
discount ceiling from 25% to 30% leaves the column type and access grants unchanged. The
owner needs to see the old and new ceiling and confirm what happens to a quote on each side
of the boundary. The design gives each rule a stable ID, names the columns it reads and
exposes its expression and owner-confirmed examples through inspection.

## 3. The design: declared rules

### 3.1 Three kinds of rule, and nothing else

A table may declare rules of exactly three kinds, on the model, next to the columns they read
(the *which*, ADR 0011):

| Kind | What it says | Example |
|---|---|---|
| `Transitions` | the moves a status column may make, and the permission a move needs when it needs one | `draft → approved` needs `quotes.approve` |
| `Invariant` | a condition over the row's own columns, held whenever the row is created or one of those columns changes | `discount_pct <= 25`; `ends_on >= starts_on` |
| `Derived` | a column computed from that row's own columns | `margin = revenue − material_cost − labour_cost` |

Each rule carries a stable id (`quote.discount-ceiling`), one sentence for the owner, and
optionally a `source` naming the document it comes from ("Pricing policy 2026, §4.2"). The
sentence is what a refusal says and what a workbench shows. It is the English fallback: a
frontend dispatches on the rule id like any other error code, so a translated sentence lives where
the application's other copy lives (ADR 0105). The platform never interprets the source.

Everything else stays code: totals over child rows, rules over time, lookups, anything that needs
a loop. So does a condition that depends on who is writing. An invariant reads the row, never the
principal, so a ceiling of 10% for one role and 25% for another is code. Aggregates over a
declared reference may come later, with their own evidence, because they bring concurrency with
them: a child's write changes the parent's figure under optimistic concurrency control.

### 3.2 A rule is data, not a function

An expression is built from column references, literals, `+ − × ÷`, comparisons, a null test,
`and`/`or`/`not`, `min`/`max` and an explicit `round(…, places)`. There are no Python callables,
no function calls and no loops.

A null test can express conditions such as “a cancelled quote states why” and “a draft
quote has no order date.”

A callable would be simpler to write and would cost every property this design exists for:
`inspect` could not serialise it, a workbench could not render it, a checker could not find a
contradiction in it, and §4.4 could not mutate it. The closed grammar is also what keeps this on
the right side of ADR 0009: it cannot grow into a language, because there is no way to write a
loop in it. The way out of it is code, not a bigger grammar.

An illustrative shape, not a fixed API:

```python
class Quote(BaseTable, table=True):
    status: str = Field(default="draft", max_length=20)
    revenue: Decimal = Field(max_digits=12, decimal_places=2)
    material_cost: Decimal = Field(max_digits=12, decimal_places=2)
    labour_cost: Decimal = Field(max_digits=12, decimal_places=2)
    discount_pct: Decimal = Field(max_digits=5, decimal_places=2)
    margin: Decimal = Field(default=Decimal(0), max_digits=12, decimal_places=2)

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

The design evaluates each service operation and verifies the resulting transaction at commit.

**`_save` is the step.** Before it stages the row and its audit record, `_save` evaluates the
table's rules on the proposed complete row, including the fields a partial update left alone:

- a `Derived` column is computed and assigned by the framework, in dependency order, and a value
  the caller supplied is never used;
- an `Invariant` is checked when the row is new, or when the write changes a column the rule
  reads, directly or through a derived value. If it is false then, the write is refused.
  Invariants are checked after the derived values they read;
- a `Transitions` column compares the row's last validated value with the new one. A move that is
  not declared refuses the write. A declared move the principal lacks the permission for is the
  existing authorization refusal. A new row starts in `initial` or is refused. An update that
  leaves the status alone can edit other fields without requiring a self-transition.

**A write that leaves a rule's columns alone is not judged by that rule.** Otherwise a rule
tightened later would make every older row uneditable: nobody could correct a phone number on a
quote, or archive it, until its old discount was fixed first. The cost is stated plainly. The
guarantee is that no write makes a row wrong and that every write touching a rule's columns
leaves the rule satisfied. It is not that every stored row satisfies every rule. `terp rules
check-data` lists the rows that do not (§3.8).

**A move may name no permission.** Then the authorization of the route or job that makes it is
all it needs. This supports transitions performed by a worker or scheduled job.

The session keeps a snapshot of the last validated values for each row. Each successful
`_save` advances that snapshot. Within one transaction, moving a quote from draft to approved
and then to ordered makes two distinct transitions. Each requires its own grant.

**Validate the transaction before committing.** Every participating row must match its
last validated state for application-managed columns. A mismatch rolls back the unit of
work and raises a programming error. This contract applies to requests, jobs, and services
called with plain SQLModel sessions. Phase 2a introduces it for all tables, ahead of rule
declarations. The design follows the per-row reference checks in
[ADR 0178](../../decisions/0178-a-reference-written-must-point-at-a-row-its-writer-can-read.md).

Inventory framework-managed writers and define how each participates. Use the observer to
measure compatibility on existing applications before enabling enforcement.

**It arrives in three steps, because it changes what existing code may do.**

1. An observing mode of the framework's pytest plugin. It refuses nothing. While an
   application's own suite runs, it reports each commit the check would refuse, with the model
   and the columns. A team runs it before it upgrades.
2. One release in which the check refuses under test and in local development, and logs a
   warning everywhere else.
3. A release in which it refuses everywhere.

Derived values are assigned before the audit record is staged, so audit and queued events
describe the values that commit. Reject two writers for the same derived column, cycles, and
rules that would write a framework-managed column such as the tenant or version. Apply existing
access checks before returning business-rule details. Derived values that reveal personal inputs
carry the relevant data protections.

Exercise this contract through a request, a job, a nested service write and competing updates
under optimistic concurrency. After a refusal, verify in a fresh session that the affected
rows and queued business events retain their prior state.

A soft-delete sets `deleted_at` and saves the retained row. Apply the usual changed-input
check to that proposed row, including framework-set values. An invariant that reads only
`discount_pct` lets an old over-limit discount stand when archiving. An invariant that reads
`deleted_at`, directly or through a derived value, is checked when the timestamp is set.
For example, a module can allow only draft quotes to be archived by declaring
“`deleted_at` is null or `status` is draft.” A hard delete removes the row and keeps its
existing deletion controls. A policy restricting hard deletes belongs in the guarded service.
[Operation-sequence guarantees](../../decisions/0193-security-boundaries-hold-across-operation-sequences.md)

A refusal uses an existing envelope, chosen by what is wrong:

- a false invariant, or a new row outside `initial`, is a `ValidationFailedError`. The request's
  own values are wrong;
- an undeclared move is a `ConflictError` (409). The request is well-formed, and the stored state
  disagrees with it.

Each `ErrorDetail` identifies the rule, column and owner sentence. It never carries a stored
value. Authorization refusals and stale writes retain their existing responses. A client may
correct a discount violation only after its authority to change that quote has been established.

The review surface lists the inputs each rule reads and marks columns declared `Personal`.
Owners can review whether the outcome is appropriate for the operation's audience.
[Personal columns](../../decisions/0190-a-field-declares-itself-personal.md)

**A derived column is not an input.** A `*Create` or `*Update` schema that declares a field a
`Derived` rule writes refuses to start the application. A service names its model and its input
schemas, so boot can compare them. Discarding the client's value silently would leave the API
contract advertising a field that does nothing.

The rules are evaluated in Python with `Decimal`, never in SQL. The two verified dialects do
arithmetic differently: SQLite, the development and test engine (ADR 0069), does decimal
arithmetic in binary floating point, and PostgreSQL does it exactly. A formula the database
computed would give two answers. So there are no generated columns, `CHECK` constraints or
triggers here. A `CHECK` backstop for a condition both dialects evaluate identically can come
later. Keeping rules out of the DDL also keeps a changed formula from becoming a schema
migration, and keeps a refusal an owner sentence rather than an `IntegrityError`.

**Numeric portability.** A numeric column that a rule reads or writes declares
`max_digits` and `decimal_places`. Cap precision at 15 significant digits for the shared
SQLite and PostgreSQL contract. Boot validation reports wider columns and missing bounds.

The guarded write path checks that each actual numeric input fits its column, including values
supplied by custom services. Check the decimal value before driver rounding can hide excess
digits. For precision `p` and scale `s`, a non-null value must be finite, be exactly
representable at scale `s`, and have magnitude below `10^(p−s)`. Thus `NUMERIC(15,2)`
accepts `12.340` and `9999999999999.99`, and refuses `12.345` and `10000000000000`.
Check derived outputs against the same bounds after the formula's declared rounding.
Use these cases through the normal API and a custom service on both supported databases.

PostgreSQL rounds such a value silently today, so this is the refusal custom code will meet
first: a price times a quantity times a rate has more decimals than its column holds. Two things
keep it cheap. The framework offers one helper that rounds a value to a named column's scale with
the declared rounding mode. And the refusal names the column, the scale it holds, the scale it
was given, and that helper.

Adopting a rule on an existing numeric column that declares no precision needs a schema migration
first. Boot names the column and says so.

A derived value is rounded to its column's `decimal_places` before it is assigned and before any
invariant reads it. Nothing rounds implicitly. Where a formula can produce more decimals than its
column holds, the declaration states the rounding with an explicit `round`. Boot computes that
for `+`, `−` and `×` from the operands' declared scales and assumes it for `÷`.

The declaration is validated at boot, fail closed. A rule that names a column the table does not
have, compares a string with a number, or requires a permission the module does not declare
refuses to start the application. So does a rule on a numeric column without the declared
precision above, and a derived column that an input schema exposes.

What can be decided cheaply beyond that is reported by verify: a state no move reaches, bounds on
one column that exclude each other, and an invariant the other invariants make always false or
always true. A condition the check cannot decide is reported as undecided, never as passing.

Before shipping a formula, specify the semantics of its operators, including nullable operands,
division by zero, the rounding mode and a result too wide for its column. A defined error yields
a typed refusal. Evaluate the same
boundary examples in memory and round-trip them on SQLite and PostgreSQL. Ship those examples
with the semantics version so a tool reproducing an older result can select the meaning used at
the time.

Database referential actions can also change a surviving row. For example, deleting a parent can
set its reference on a child to null without a service save on the child. Before accepting a
rule that depends on such a column, verify its outcome through a real parent deletion. Until
the runtime can enforce that combination, explain the unsupported declaration at boot. A team
can implement a custom deletion flow that updates the affected children in the transaction.
A data migration uses the maintenance engine. Its post-migration checks must cover the rows
it changes, and §3.8 gives them a command. [Reference deletion behavior](../../decisions/0133-a-reference-declares-what-a-delete-of-its-target-does.md)

### 3.4 Readable through inspect, and pinned like who-can-reach-what

`terp inspect schema` gains, per table, a `rules` list: id, kind, the columns read and written,
the expression or transition map, the owner sentence, the source, and a content hash. The
executable identity covers the rule kind, column bindings, relevant types, evaluator semantics
version and the normalized rule body. For a transition this includes its initial state,
permitted moves and required permissions. Where a rule reads another derived value, retain
the deciding rule versions together.
Keep each release's pin so a historical write can be explained. The audit record of a write
carries the hashes of the rules that decided it. The log line of a refusal carries the hash
of the rule that refused it.

The rules of every table are also rendered as a committed `rules-surface.json`, and a verify check
diffs the composed rules against it, as ADR 0139 does for `authz-surface.json`. A ceiling moved
from 25 to 30, a transition added, a formula changed: each fails the gate until the record
matches again. An app lists `rules-surface` under `[tool.terp.verify] pinned`, so a missing
record is refused too.

**Changes to a rule require owner approval.** Regenerating the pin records what the
application declares. Acceptance is recorded separately against the rule's content hash.

- **The check says whose decision it is before it says what to do.** A changed rule is a
  person's to accept. If a line is not intended, change the code. If every line is, the person
  who owns the rule accepts it and the record is written again in the same change. The
  template's `AGENTS.md` documents who may update the pin and record approval.
- **Approval is its own record.** `rules-approvals.json` lists, per rule id, the content hash
  that was accepted, by whom and when. Confirmed examples are listed the same way (§4.3). In
  Terp Studio the owner approves and Studio writes the entry. Without Studio the approver adds
  it in the change, and the team protects the file with required review, for example a
  `CODEOWNERS` entry.
- **Retirement has an approval too.** Compare the proposed surface with the pin at the base
  of the change and, for release, with the last released pin. For each rule ID removed, record
  the same approver and time against its previous content hash and the outcome `retired`.
  An approval for the active rule covers only that version in use. The retirement entry stays
  available to the release check even when the final rule, its module and its pin are removed.
  Phase 5 applies the same comparison to tracked decisions.
- **The check reports two things separately.** Whether the code matches the record is red in
  `full` and `release`. Missing approvals for current hashes or retirements are named in
  `full` and red in `release`. If a previous release carried a pin and it cannot be read,
  the release comparison is incomplete. First adoption starts with an empty previous set.
- **Protect the approval file.** An approval entry names the approver and appears in the diff.
  Required review of that file establishes who can accept it.

**The deployed rules are the approved rules.** As
[ADR 0212](../../decisions/0212-an-app-compares-the-routes-it-serves-with-its-record-before-it-serves.md)
does for routes, the app compares the rules it composed with `rules-surface.json` when it starts.
Outside local development a difference is a `BootError`. The check before release runs the code
it judges, so the running app is the record's second reader.

The permission a move names has to be one the module already declares. Who holds it stays in
`authz-surface.json`, which move needs it is in `rules-surface.json`, and both are pinned.

### 3.5 The vocabulary lives in the spec

The JSON shape `inspect` emits and the surface pins is a declaration vocabulary read by two
programs, so it is published in terp-spec as `rules-declaration.schema.json` and versioned with
the spec. The framework keeps the enforcement; the spec keeps the words. A reader that meets a
kind it does not know reports it and carries on, per ADR 0111's degradation test. That is a
reader's rule. A runtime asked to enforce a kind it does not know refuses to start.

The approval record (§3.4) and the example file (§4.3) are read and written by the same two
programs, so their shapes are published with it.

### 3.6 A legibility contract, not conformance

Declaring rules is optional. An application that declares none passes every gate exactly as it
does today; its rules are code, and a workbench says plainly that it cannot show them. The
platform never decides whether a rule is right. It enforces truth about the application's own
statement (ADR 0111 §1): a declared rule is enforced, pinned and shown.

Read against ADR 0006's quadruple:

- the typed declaration with a safe default is `Rules`, whose absence changes nothing;
- the fail-closed runtime half is §3.3, at the write, at the commit and at boot;
- the escape is not to declare, which leaves the logic in code where it is today;
- the build-time half is `no_manual_derived_writes`: a module that assigns a `Derived` column by
  hand contradicts its own declaration. Under ADR 0122 it is not added on analogy with
  `no_manual_actor_stamping`. It lands when an application shows a need for that diagnostic.
  The data is protected either way, because `_save` overwrites the column and the
  commit refuses a change made after it.

### 3.7 What a workbench does with it

The fields arrive with their reader (ADR 0122 §3). A workbench such as Terp Studio:

- draws the rules on its data-model view: the formula on a derived column, the owner sentence
  beside a guarded column, a state diagram for a transitions column;
- shows a changed `rules-surface.json` as plain-language changes for the owner to approve ("the
  discount ceiling changes from 25% to 30%"), and writes the owner's approval as an entry in
  `rules-approvals.json` (§3.4);
- shows each example as confirmed, proposed or failing, for the revision under review (§4.3),
  and asks the owner for the outcome of an input the coverage check proposes (§4.4);
- shows a refusal as its owner sentence, not its rule id;
- shows the owner a distinguishing example when a surviving rule mutant (§4.4) has one.

### 3.8 Stored rows are checked against the rules, on demand

Rules hold a write. They say nothing about rows written before a rule existed, by a migration, or
under an earlier formula. A read-only command, working name `terp rules check-data`, evaluates
every declared rule against the stored rows and reports per rule how many rows fail an
invariant, hold a status the declared moves do not name, or carry a derived value the current
formula would not produce. It also reports stored numeric inputs and outputs outside their
declared precision or scale. Check the stored value before ORM result conversion can round it.
For example, a legacy SQLite row containing `12.345` in `NUMERIC(15,2)` must be reported even
if the ordinary model reader returns `12.35`. A scan can report only what storage retained.
The command reads as a migration does, across tenants. It reports counts and row ids,
never values, and it writes nothing. It has three uses:

- before tightening an invariant, to count the rows that already fail it. They stay editable,
  and the first edit that touches the rule's columns has to put them right (§3.3);
- after a data migration, as the post-migration check of §3.3;
- after a formula change, to list the rows that still hold the old result.

The command reports and never repairs. Recomputing rows is a data migration the team writes,
because recomputation can rewrite history, such as the margin of a quote approved last year. Run
the command against a copy of production before a release that changes a rule.

## 4. The design: testing strategy

### 4.1 Why not 100% coverage and 100% mutation everywhere

1. **Some mutants cannot be killed.** A mutant that does not change behaviour (an equivalent
   mutant) survives every test, and deciding equivalence is undecidable in general. A 100% bar
   therefore needs an exemption.
2. **Assertions can pin implementation details.** Snapshotting current outputs can kill
   mutants while preserving an incorrect result and making a refactor require a test rewrite.
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

Each declared rule comes with concrete cases and independent expected outcomes. Store the
synthetic inputs and expectations once as application-owned test data. Ordinary tests in the
module's test tree (ADR 0119) exercise them. Inspection and export can read the same cases.

- "A discount of 25%: accepted. 26%: refused."
- "An approved quote moves to ordered with `quotes.place`. A draft quote does not."
- "Revenue 1000, material 400, labour 250: margin 350."

Examples are the oracle because they are not derived from the declaration. An owner can confirm an
example without reading an expression, and an example that disagrees with its rule means one of
the two is wrong, which is exactly the finding.

**An example is independent only if someone other than the rule's author stands behind it.**
A rule and its test can share the same mistaken interpretation. Record who confirmed the
expected outcome. Each example carries a status:

- *proposed*: written by whoever wrote the rule. It runs as a test and counts for nothing more.
- *confirmed*: a named person accepted this input and this outcome. The acceptance is an entry in
  `rules-approvals.json` (§3.4), keyed to the example's id and content hash.

Changing a confirmed example's input or outcome changes its hash, so it needs approval again,
like a changed rule. A change that edits a rule and a confirmed example of that rule together is
named by the check as exactly that: the rule and its evidence moved in one change. `inspect` and
a workbench show a proposed example as proposed.

The cheapest way to a confirmed example is to split the work. The tool knows which inputs matter:
the boundary of each comparison, a case with every operand of a formula present, each declared
move (§4.4). It proposes those inputs, and the owner supplies the outcomes. A generated input is
fine. A generated outcome would agree with the declaration by construction (§7).

### 4.4 Example coverage first, targeted rule mutation as its measure

The closed grammar lets the checker suggest useful example inputs without running the code:

- a comparison needs a confirmed example on each side of its boundary. For `discount_pct <= 25`
  on a column with two decimals that is 25.00 and 25.01;
- for a formula, look for a case with every operand present, non-zero and distinct, and for a
  `round` look for a case on its rounding boundary. These are heuristics. For
  `total = quantity × unit_price`, both `1 × 3 = 3` and `2 × 3 = 6` meet the first criterion.
  Only the second example detects dropping `quantity`, which would return `3` in both cases;
- a declared move needs one example that makes it, one that is refused for lack of its
  permission where it names one, and one undeclared move from the same state that is refused;
- a null test needs one example with the value present and one with it absent;
- an invariant needs one example that edits an unrelated column on a row that already fails it,
  and is accepted (§3.3).

The `rule-examples` check compares the examples a rule has with that list and reports what is
missing in the owner's language: "Nothing says what happens at exactly 25%", or "no example has a
labour cost, so a formula that adds it instead of subtracting it would pass". It reads
declarations and example data and runs no test, so it is cheap enough for `quick`. A satisfied
criterion reports that the input shape is covered. Keep the check advisory until the pilot
measures which faults these examples detect and which pass despite meeting the criterion.

Targeted mutation stays in the pilot as the measure of that check. For each changed rule in the
pilot, try a small, deterministic set of edits to the declaration.

- each comparison boundary moved (`<=` to `<`, `25` to `24` and to `26`);
- each arithmetic operator swapped, and each `round` place count moved by one;
- each null test inverted;
- each declared move removed, one undeclared move added, and each required permission dropped.

For pure expressions, run the independent examples against the changed expression in memory.
Use operation-level tests when the observable result depends on permissions or persisted state.
Compare the additional faults found, elapsed time and review effort with the baseline checks.
An edit that survives on a rule whose examples the coverage check called complete is a gap in
the coverage list, and the list is what gets fixed.

A surviving edit warrants investigation. Where a valid input distinguishes the two results,
show the owner the input and ask which result is intended. Some edits have identical observable
results throughout the allowed domain, including when another rule excludes the distinguishing
inputs. Record equivalent or unresolved cases separately. The pilot runs in advisory mode.
A later decision can make a narrowly defined class blocking once its benefit and cost are known.

### 4.5 Hand-written code: no new survivor per change

For the code an application writes by hand, mutation runs over the lines a change touches, with
tests selected by which ones cover the mutated line. mutmut (Python) and Stryker (TypeScript) are
the reference realisation. It runs in the `full` and `release` profiles.

The bar is a ratchet, not a percentage: **a change may not add a surviving mutant.** A survivor is
either killed by a test or marked equivalent with the tool's own suppression comment carrying a
reason, counted in the module's escape-hatch budget like an `arch-allow` marker (ADR 0103:
escapable by proof, never quietly). Survivors on lines the change did not touch are not its debt.
A score over the whole codebase was rejected, because a new survivor hides behind old kills.

Select tests per mutant, stop at the first failing test and cache results by content hash.
Prefer simplifying an equivalent expression before adding a justified suppression.

A flag that only changes DDL, such as an index or a delete action, survives every behavioural
test. A test that inspects the migrated schema kills it.

The framework's own code takes the same per-change ratchet, plus a periodic full run whose score
may only rise.

### 4.6 Coverage: a report and a floor, never a target

The framework keeps `fail_under = 100`. An application gets no coverage percentage to reach. It
may adopt a floor that only rises, as a ratchet against decay, but coverage is never offered as
evidence of adequacy; the spec already says it is not.

### 4.7 The lane

The existing `test-adequacy` lane is recommended. Count only checks that ran and produced the
evidence the lane requires. The pilot reports targeted mutation separately while its value is
being measured, and the `rule-examples` check composes nothing into the lane while it is
advisory. The proposed changed-code ratchet in §4.5 has its own adoption decision.
Choosing a backend adoption level does not select a mutation gate.

## 5. The plan, in phases that each end somewhere shippable

Phases 1 and 2a can run side by side. Phase 2b follows phase 2a. During implementation and
CI, verify each change with local test suites and owner-confirmed examples.

### Phase 0 — quote acceptance criteria

The owner confirmed these outcomes for ordinary service code and declared rules.

- A 25.00% discount is accepted and 25.01% is refused. A quote with a historical 30%
  discount allows an unrelated edit or a correction to 25%. Changing its discount to 29% is refused.
- Margin is revenue less material and labour costs. Revenue of 100.00 and costs of 37.40 and
  22.50 give a margin of 40.10. A partial edit retains omitted inputs and recalculates margin.
- A new quote starts in draft. Moving between draft and approved requires `quotes.approve`.
  Moving from approved to ordered requires `quotes.place`. A direct move from draft to ordered
  raises `ConflictError`. A permitted move without its grant raises `PermissionDeniedError`.
- After a refusal, a fresh session sees the previous quote and version, or no quote for a
  refused create.

### Phase 1 — mutation on changed code

- [ ] Diff-scoped mutation for Python (mutmut) and TypeScript (Stryker): changed lines only, tests
      selected per mutant, parallel shards, results cached by content hash (§4.5). Check what
      each tool selects on its own. Where it selects by file, a changed-line selector is part of
      this task.
- [ ] Guidance to refactor an equivalent mutant away first, and the suppression that remains
      counted in the escape-hatch budget.
- [ ] `diff-mutation` composes the `test-adequacy` lane in `full` and `release`; measure run times
      on the framework and on `apps/example`.
- [ ] A periodic full run of the framework, its score ratcheted.

### Phase 2a — the write path holds every row it commits

This phase establishes the transaction guarantees used by declared rules.

- [ ] Ship the prototyped `pytest --terp-report-writes` (§3.3). The observer reports the test, mapped
      model and changed columns for committed ORM writes outside a service save. It covers
      both plain SQLModel sessions and request sessions, including writes made by test
      fixtures. Publishing the observer precedes enforcement.
- [ ] Integrate the prototyped quote persistence checks on the request session. Check for one commit on create
      and partial update, then read the stored quote in a fresh session after each success
      or refusal.
- [ ] Add operation-level regression tests for atomic persistence and rollback (ADR 0193).
- [ ] Inventory framework-managed writers and document their participation in commit validation.

- [ ] The per-row validated snapshot and the check before the commit of every write unit, for
      every table: in a request, in a job, and on a plain session a test hands to a service
      (§3.3).
- [ ] The release that refuses under test and in local development and warns elsewhere, then the
      release that refuses everywhere.
- [ ] Update ADR 0015 with the transaction contract and publish migration guidance in the
      changelog before enabling enforcement.

- [ ] The example app's and the template's suites run against it, with what broke recorded.

### Phase 2b — declared rules, core

- [ ] terp-spec: `rules-declaration.schema.json`, with the shapes of the approval record and the
      example file, released first (the coupled-CI order).
- [ ] terp-core: `Rules`, `Transitions`, `Invariant`, `Derived`, `col` and the null test;
      evaluation at `_save` against the validated snapshot, with an invariant judged only when
      the row is new or its columns change; moves that name no permission; a false invariant in
      the `ValidationFailedError` envelope and an undeclared move as a `ConflictError`; boot
      validation of numeric declarations and derived columns in input schemas. Exercise the
      value bounds on API and custom service writes, and compare with `rules-surface.json` at
      startup.
- [ ] Exercise soft-delete through the service with a 25% discount ceiling and the draft-only
      archive invariant from §3.3. Start with two historical quotes at 30%. Archiving the draft
      succeeds. In a fresh session, verify its deletion timestamp is set and its discount is
      still 30%. Archiving the approved quote raises `ValidationFailedError` for the archive
      invariant. In a fresh session, verify the quote is still visible with a null deletion
      timestamp and its original version.
- [ ] terp-core: the helper that rounds a value to a column's scale, and the numeric refusal
      that names the column, both scales and the helper.
- [ ] terp-cli: the `inspect schema` projection, `rules-surface.json` under `pinned`, a verify
      check that diffs it and words its refusal as §3.4 says, and `rules-approvals.json` with the
      report of unapproved current hashes and retirements. Test removing the sole released rule
      and its pin. Release must fail until an approval names its prior hash and retirement.
- [ ] terp-cli: `terp rules check-data` (§3.8), including legacy numeric values outside the
      declared precision or scale.
- [ ] `apps/example`: one table declaring a flow, two invariants and a derived column, with
      examples.
- [ ] A `terp guide` topic and two template `AGENTS.md` lines: reach for a declaration before a
      service branch, and never write the record or an approval to turn the gate green.
- [ ] Run the same confirmed quote outcomes and request-persistence checks locally against
      the declared implementation.
- [ ] Verify that an owner can review a rule change. Plant a moved threshold, a flipped operator, a
      removed move and a rule approved by its own author, without saying which. Record how many
      an owner finds, and how fast, from the plain-language change list and from the code diff.

### Phase 3 — examples and rule mutation

- [ ] The `rule-examples` coverage check (§4.4), advisory, and example status in `inspect`.
- [ ] The contradiction checks of §3.3 in verify.
- [ ] A mutant generator per kind, normalising known equivalents.
- [ ] Run pure examples in memory and select affected operation tests for stateful rules.
- [ ] Grade the two multiplication cases in §4.4 separately for static example coverage and
      detection of the dropped operand.
- [ ] Report distinguishing examples, equivalent edits and unresolved cases separately.
- [ ] Compare marginal defects caught, elapsed time and review effort before proposing a gate,
      for the coverage check and for mutation separately.

### Phase 4 — the workbench (lands in terp-studio)

- [ ] Rules on the data-model view: formula, owner sentence, state diagram.
- [ ] A changed `rules-surface.json` shown as plain-language changes for the owner to approve,
      and the approval written as an entry in `rules-approvals.json`.
- [ ] Examples shown as confirmed, proposed or failing for the revision under review, and the
      owner asked for the outcome of a proposed input.
- [ ] Refusals shown as their owner sentence; surviving rule mutants shown as questions.

### Phase 5 — the decision set (the adoption proposal's third level)

The [backend adoption proposal](backend-adoption-and-custom-code.md) lets a module name the
decisions an owner reviews, including ones implemented in custom code. None of that was in a
phase. That proposal's billing trial runs on a prototype. This phase builds the decision set for
real, and only if the trial supports it.

- [ ] The module-level declaration of a decision set, and its vocabulary in terp-spec.
- [ ] `terp inspect` for a module that owns no tables, and decisions in `rules-surface.json`
      under the same ids as the schema view.
- [ ] Custom entries: the named operation, the implementation symbol, and examples run through
      that operation. An entry reads "described, not verified" until confirmed examples pass at
      the revision under review.
- [ ] Compare tracked decisions against the base of the change and the last release's record.
      Exercise a move to custom code under the same ID and a retirement that removes the last
      decision from review. Check approval of the replacement or retirement respectively.

## 6. Decisions to record

- With phase 2a: an ADR amending ADR 0015, so that the commit holds every row to the state its
  last `_save` validated. It does not wait for the rules.
- Use the phase 0 acceptance criteria in the ADR for declared rules (the three kinds, the two enforcement
  points, pinning, the approval record and who may write it, the 15-digit precision rule, the
  spec vocabulary).
- In that ADR, two choices made for the people who use the framework, each with its cost. An
  invariant is judged only when the row is new or its columns change, so old rows stay editable
  and a stored row may fail a rule until someone touches it. An undeclared move is a conflict,
  not a validation refusal.
- With phase 1, record the decision on the changed-code ratchet and coverage floor. After phase
  3, decide whether the `rule-examples` check blocks, and which targeted rule mutations, if any,
  justify a blocking check.
- Whether `no_manual_derived_writes` enters the catalog, on ADR 0122 evidence only.
- A spec release for `rules-declaration.schema.json`; later, on run-time evidence, whether
  `test-adequacy` becomes required.

## 7. Deliberately not in scope

- **A rules engine or a DMN runtime.** The three rule kinds use the existing service runtime
  and preserve ADR 0009's authoring model.
- **Rules enforced by the database** (generated columns, `CHECK`, triggers). Different arithmetic
  on the two verified dialects, a migration per formula change, and refusals no owner can read.
- **Rules as Python callables.** Not inspectable, renderable, analysable or mutable.
- **Rules as rows the owner edits at runtime.** That would be the one path in the platform that
  changes behaviour without a diff. An owner who wants a different ceiling asks for it, and the
  change arrives pinned.
- **Tests generated from the declaration as the oracle.** They agree with the declaration by
  construction, so they only test the evaluator, which the framework tests once. Generated
  inputs with outcomes a person supplies are in scope (§4.3).
- **Rules that read the principal.** A ceiling that depends on the writer's role is code (§3.1).
- **An exact decimal type for SQLite.** Storing decimals as text there breaks sums and ordering.
  The 15-digit bound of §3.3 is the smaller change.
- **100% coverage and a 100% mutation score everywhere** (§4.1), and **a mutation-score percentage
  per application** (§4.5).
- **Cross-row aggregates and rules over time**, until evidence asks for them.

## 8. Open questions

- The API shape: a `ClassVar` on the model, or a declaration beside the `ModuleSpec`. The decision
  set of phase 5 needs a module-level home either way, because a module can own decisions and no
  tables.
- The default rounding mode of `round`. The place count is settled: it is the column's
  `decimal_places` (§3.3).
- Whether recomputing rows after a formula change gets a data-migration template.
  `terp rules check-data` reports the rows (§3.8).
- Who may confirm an example or approve a rule when the owner is not a user of the repository,
  and how a workbench phrases a surviving mutant as a question.
- Whether an unapproved rule blocks a merge (`full`) or only a release. §3.4 proposes only a
  release.
- Whether the commit backstop compares every column an application can set or a cheaper digest,
  and what it costs on a unit of work that writes many rows. Use the observer to measure application compatibility before upgrading.
- Whether a comparison with a null operand passes, as a SQL `CHECK` does, or refuses. With the
  null test in the grammar, a rule can say which it means.
- The run-time budget for `diff-mutation` in `full`, and whether rule mutation is cheap enough for
  `quick`.
- For aggregates later: what evidence justifies them, and how an OCC conflict on the parent row is
  handled.
