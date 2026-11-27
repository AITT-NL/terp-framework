# Backend adoption and custom code

**Proposed default.** Once the decision-set tooling ships, new applications and newly
scaffolded backend modules start declaration-first. Existing modules keep their current
behavior on upgrade. The billing example below illustrates the proposed inspection view.

## What a team chooses

A team chooses how much of its business logic Terp executes and how much an owner can inspect.
Custom Python is a supported way to build business behavior at every level. It runs under the
same authorization, tenancy where applicable, and guarded-write controls as a declared rule.
The proposed transaction checks apply to custom code and declared rules alike.
Using custom code for a business decision is an ordinary authoring choice and requires no
architecture exemption. [Authoring model](../../decisions/0009-authoring-model-and-opinionation-boundary.md)

| Adoption level | What the team authors | What the owner can inspect |
| --- | --- | --- |
| **Declaration-first (default)** | List each business decision the owner needs to review. Use executable declarations wherever the rule language fits. Record custom Python under the same decision inventory. | The rule or custom implementation for each decision, its examples, and changes to what the owner can inspect. |
| Selective business rules | Any mix of custom code and declared calculations, row constraints and status transitions. Terp enforces each declaration on the guarded write path. | Each declared rule, its inputs, and the changes to it. The view makes no completeness claim about the module. |
| Code only | The team writes its domain logic in application modules. | The existing access and schema views. A pricing calculation in service code is reviewed in that code. |

All three levels describe how a module is authored. None is a package profile. Every application
runs the base profile at every level: core, auth, identity, users, groups, access and audit, the
set the template requires unconditionally.
[Base profile](../../../packages/backend/capabilities/README.md)

A team could use declaration-first billing, selective rules in purchasing, and a forecasting
module written in Python in the same application. A declaration takes effect as soon as the
application adopts it. A module-level setting cannot turn off a rule still attached to a table.
Moving a module to code only therefore includes retiring or replacing its declarations.

A new project records declaration-first as its application default. A module inherits that
choice unless it explicitly selects another level. The module scaffold records the chosen
level and creates the decision inventory when declaration-first applies. In an older project
with no recorded default, the scaffold also starts new modules declaration-first. Existing
modules in that project retain their current behavior. A team can migrate them individually.
Before changing an existing project's default, record explicit levels for modules that
should keep their current level.
The inspection view shows the effective level. Authorization, tenancy, audit and release
assurance apply across all three choices.

## What declaration-first adds

Consider a billing owner who asks to review three decisions before a release. This is an
illustrative reading of the proposed `terp inspect` output for that module.

| Decision | How it is implemented | What the owner reads |
| --- | --- | --- |
| Quote margin | Declared calculation | “Subtract material and labour cost from revenue.” Revenue 1,000, materials 400 and labour 250 give a margin of 350. |
| Discount ceiling | Declared constraint | “A discount above 25% is refused.” A change to 30% would allow a 27% discount that was previously refused. |
| Freight estimate | Custom Python | “Freight depends on the carrier schedule.” The view points to the service method and a worked example the owner can review. The algorithm lives in that method. |

The module declares its decision set in code, under stable, unique IDs. The declaration is
module-level, because a module can own decisions and no tables. Its exact shape is an open
question in the business-rules draft. A declared entry refers to the executable rule by ID. A
custom entry names the public operation that uses it, the implementation symbol, and the worked
examples that support its description. A rename preserves the decision ID. Duplicate IDs, two
implementations claiming the same decision, and unresolved references are verification errors.
In a declaration-first module, a missing inventory is a verification error. A new module
with no business decisions can start with an explicit empty inventory. Each declared rule
must appear by ID as the module grows. The owner reviews whether the inventory covers the
business decisions made in custom code.

The view says how far each line can be trusted:

- A declared rule is *enforced*. The framework evaluates the expression the owner reads.
- A custom entry is *described*. Its sentence is its author's account of code the view does not
  read. The source link locates the implementation at the reviewed revision, and a change inside
  a helper can leave that link intact.
- A custom entry is *verified for this revision* only when examples a person confirmed pass
  through the named operation at the revision under review. Otherwise the view shows the expected
  outcome and labels it unverified for that revision.

An example a person confirmed is recorded as confirmed. An example written by the author of the
rule or the code is shown as proposed, because an author who misread the decision wrote the
example from the same misreading.
[Example status](declared-business-rules-design-and-plan.md#43-examples-are-the-oracle)

Today's `terp inspect schema` discovers tables from migration trees. A carrier quote returned
by a service might never be stored. The proposed module view therefore reads the module's
decision inventory even when it owns no tables. Table decisions also appear in the schema view
under the same IDs. Inspection reads descriptions and synthetic example data without invoking
the carrier service or reading customer rows. Studio can mark an unfamiliar rule kind as
unsupported while showing the rest. A runtime asked to enforce an unknown executable rule must
refuse it at startup. Outside local development it also refuses to start when the rules it
composed differ from the committed record, as it already does for routes.
[Current schema inspection](../../../packages/backend/cli/src/terp/cli/__init__.py)

Reuse the business-rules draft's proposed `rules-surface.json` review. It should show changes
to the named set as well as to the rules themselves. Moving the margin calculation to Python
keeps its ID and produces a reviewable change such as “Quote margin is now calculated in
custom code.” Removing it from the set produces “Quote margin is no longer tracked.” Returning
the whole module to code only shows which decisions leave review together.

Verification compares the composed application with the proposed pin. Change review also
compares that pin with the previously reviewed one: the pin at the base of the change, and at a
release the pin the last release carried. This second comparison preserves the removal report
even when a change deletes the module, inventory and pin together. First-time adoption shows the
initial set. A missing pin for an opted-in module or a failed inspection is an error to fix. An
explicit retirement is a decision to review. If the previous pin is unavailable, report that the
comparison could not be made. Coverage is relative to the set the team named.

A passing verification check establishes agreement with the pin. Acceptance is an entry
in `rules-approvals.json`, written by Studio when the owner approves or by the approver in
the change. Approval covers the change the owner saw. Moving a decision to Python under the same ID
requires approval of its new description and implementation reference. Retiring a rule or tracked
decision records its ID, previously released hash and the outcome `retired`. Removing the last
entry in a module still requires this approval at release.
[Approval](declared-business-rules-design-and-plan.md#34-readable-through-inspect-and-pinned-like-who-can-reach-what)

The declaration, evaluator and inspection view share one representation of a formula. A custom
method stays ordinary Python. A developer can add behavior that needs a loop, a lookup or a new
algorithm immediately, without expanding the rule grammar. The existing proposal owns the
expression language, enforcement point and inspect format. A format consumed by both the CLI
and Studio belongs in `terp-spec`. [Declared business rules](declared-business-rules-design-and-plan.md)
· [Framework and shared contracts](../../decisions/0203-the-rules-belong-to-the-framework-and-only-the-contracts-are-neutral.md)

## Moving between levels and leaving Terp

Start by moving one decision at a time. Capture its expected outcomes, run them through the
public operation before and after the change, and switch to a single implementation in the
same change. The same procedure works in reverse. For a stored calculation, decide which
historical values to keep and which rows to recompute. If approved quotes retain their original
margin, verify that editing an unrelated field on an approved quote preserves it. An unconditional
derived field recomputes on every save. Use custom code when that behavior would alter history.
For changes that affect persisted values, specify how old and new writers coexist or drain old
workers before switching. Verify what a rollback does to rows already written by the new version.
Before tightening a constraint on an existing table, count the stored rows that already fail it.
The business-rules draft proposes a read-only command for that, `terp rules check-data`, to run
against a copy of production. An invariant judges a write when it creates the row or changes
one of the invariant's inputs. A team can still archive a quote whose old discount exceeds
today's ceiling. If the team also requires a quote to be in draft when archived, its invariant
reads `deleted_at` and `status`, and archiving an approved quote is refused.
Decide who fixes the old discounts and when. Declaring a rule on
an existing numeric column that states no precision needs a schema migration first.

Before an existing application moves to the release that holds every committed row to its save,
run the observing mode over its own test suite. It refuses nothing and lists what the check
would refuse.

Test the cost of leaving on the first calculation. Give another developer the exported margin
expression, numeric and rounding semantics, and owner-confirmed input/output examples. Keep
these cases as application-owned data that the tests, inspection view and exit exercise can
all read. Ask the developer to reproduce the results in plain Python without importing Terp.
Include a rounding boundary for a rounded result and a refusal case for the discount ceiling.
Keep the rule ID and evaluator semantics version with the export. Ruled numeric columns declare
at most 15 digits of precision. The guarded write checks that each value actually fits the
declared precision and scale, including writes from a custom service. The exit examples include
an excess fractional digit. The stored-data scan reports older rows outside the bounds.
That exercise measures portability of the rules. Moving accounts,
grants, stored data and transactional enforcement to a different backend is a separate migration
with its own costs.

## Implementation verification

1. **Verify the quote policy.** During implementation, check ordinary service
   code and selective declarations locally against the same owner examples. Include an
   omitted labour cost, an off-by-one discount ceiling and a constraint enforced on create
   but skipped on update.
   [Quote acceptance criteria](declared-business-rules-design-and-plan.md#phase-0--quote-acceptance-criteria)
2. **Start with inexpensive checks.** Resolve IDs, column types, permissions and formula
   dependencies at load or verification time. Report which boundary examples each rule lacks.
   Keep this input-coverage check advisory until the pilot measures its misses. In a line-total
   formula, a quantity of one can hide an omitted multiplication. Run independent examples for affected
   rules and their dependents. A shared evaluator change reruns the shared conformance cases and
   all rule examples. For shared custom code, run the consuming modules' suites. Fall back
   to the application suite if the consumers cannot be determined.
   Test the evaluator, create and update paths, and persisted state after refusal in the
   framework suite. Custom behavior keeps application tests at its public entry point.
3. **Measure the value of mutation.** Compare defects that escaped the cheaper checks, elapsed
   time, and time spent investigating equivalent changes with and without targeted mutation.
   Use that evidence to decide which checks earn a blocking role. For a pure formula, try an
   operator change against its examples in memory. Keep database tests for failures that
   depend on a transaction or an adapter. For hand-written code, select tests per mutant and
   run shards in parallel.
4. **Trial declaration-first in billing.** Plant a changed threshold, a decision moved to custom
   code, a decision removed from review, and a rule whose record and approval were written by
   its own author. Do not tell the owner which. Record how many the owner finds, and how fast,
   from the inspect output and from the code diff. Include a tableless module, a change to a
   custom helper, and complete removal of a module's review inventory. Exercise an existing
   code-only app alongside it and complete the exit exercise. Verify the default on a fresh
   project, an explicit lower level, and an upgrade of an existing project. Use the trial to
   refine diagnostics and decide which example checks should block a release before shipping
   the declaration-first default in phase 5.
   [Business-rules implementation plan](declared-business-rules-design-and-plan.md#5-the-plan-in-phases-that-each-end-somewhere-shippable)
