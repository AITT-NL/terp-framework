# 0141 — The gate scans every deployable, not only the mounted one

- **Status:** Accepted and implemented. `check_app` / `assert_app_clean` take any number
  of `ScanRoot`s; `RULE_ROOT_KINDS` records each rule's applicability; the escape-hatch
  budget is shared across the scanned roots; a project declares its extra roots once in
  `[tool.terp.arch]` and both entry points read it. The template declares
  `control_plane`, and this repository's own gate scans the example app's. Held by
  `tests/architecture/test_scan_roots.py`, `tests/architecture/test_arch_harness.py` and
  `tests/architecture/test_check_json.py`.
- **Date:** 2026-09-17
- **Relates:** [ADR 0136](0136-a-security-rule-does-not-stop-at-the-module-tree.md) (the
  same mistake one level down: a rule that stopped at `modules/`), [ADR 0084](0084-runtime-applicability-classification.md)
  (a rule's properties are recorded, not assumed — which is the shape `RULE_ROOT_KINDS`
  copies), [ADR 0083](0083-findings-envelope-and-evaluated-rule-inventory.md) (the
  evaluated-rule inventory this has to keep honest), [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md)
  (why this adds no rule), [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md)
  (the profile an app extends but cannot rewrite, which is why the declaration exists)

## Context

`assert_app_clean(app_root, *, package, budget_path)` took one root. So the code an
application could hold to the eighty rules was exactly the package `create_app` mounts,
and everything else in the repository was outside the gate by construction rather than
by decision.

Plenty of repositories have something else. A worker that runs where the application
cannot. A publisher. A CLI. A sidecar that speaks a protocol the app has no business
speaking. The platform's own guide already tells authors to build one — `terp guide
package-boundaries` is a page about a second top-level package and how to keep the two
from importing each other — so this is not an exotic shape the harness had never met.
It is a shape the harness documents, recommends, and then does not scan.

The consequence has a direction, and the direction is the problem. The second deployable
is not a random remainder: it is disproportionately **where the dangerous code is**. It
is the thing that holds a credential for a system the app does not own, opens a
connection to a database nobody on the team administers, assembles a statement as text
because the foreign schema is not modelled, and speaks to the network directly because
there is no capability between it and the wire. Those are the exact subjects of
`no_hardcoded_credentials`, `no_dynamic_sql` and `no_raw_outbound_http` — and ADR 0136
had just finished widening all three, from `app/modules/` to the whole scanned root, on
the argument that a security rule does not stop at a directory. It still stopped at a
root.

What a repository does instead is visible and predictable: it hand-writes the rules it
misses. A worker package acquires a test module with three or four bespoke AST scans —
an import allowlist, a check that SQL literals stay inside the connector layer, a check
that a frozen value object holds no list — each of which the harness already implements,
better, with a file and a line and a fix recipe. That is a rational response to a
missing feature and a bad place to end up: the component with the most consequence ends
up governed by the fewest rules, written by the smallest number of people, reviewed
least.

**And the second package is not only the exotic case.** The scaffolded shape has had
two Python packages since it existed. `terp new` writes `app/` and `control_plane/`
beside it, and the control plane is where the application's permissions, operations,
event catalog and job catalog are declared — the template's own files say as much. The
generated `test_architecture` calls `assert_app_clean("app", …)`. So the declarations
that decide what every route requires have been outside the gate in every Terp
application ever generated, not because anyone decided they should be but because the
harness took one root and `app` is the one it was handed. The example app in this
repository is the same shape, and its `control_plane/` had never been scanned either.

**The report inventory was already half-admitting this.** `terp check --package engine`
has always worked in the sense that it runs, and the guide teaches it with an honest
caveat attached: read a green as "the rules that apply are clean", and do not publish it
as a Terp Standard claim, because the report names the whole registry while a package
that is not a Terp app cannot exercise most of it. A caveat in prose is where a missing
distinction goes to live.

## Decision

**A scanned root has a kind, and the kind decides the rules.** `check_app` and
`assert_app_clean` take any number of roots. A bare path is an `APP` root on the call's
`package`, which is what every existing call site already means, so nothing about the
one-root spelling changes. A `ScanRoot(path, package=..., kind=RootKind.COMPANION)` is a
second deployable: shipped from this repository, not mounted by `create_app`.

**Applicability is recorded per rule, not inferred.** `RULE_ROOT_KINDS` maps every rule
to `EVERY_ROOT` or `APP_ROOT_ONLY`, in the same key space as `GUIDE_TOPIC_BY_RULE` and
locked by the same kind of completeness meta-test, so a new rule cannot arrive
unclassified. The line is not "security rules travel and the rest do not":

> **A rule applies to every root when its invariant holds for any Python that ships, and
> to app roots only when its invariant is a property of being a mounted Terp
> application** — of a module, a route, a response, a table, a migration, an event, a
> job, or the guarded session.

A worker has no route whose response model could be wrong. It very much has a hardcoded
credential, an f-string `text(...)`, a raw HTTP client, a naive `datetime`, a `print()`
where a log line belongs, and a frozen dataclass holding a list. Sixteen rules travel;
the rest stay with the application contract they describe.

Two neighbouring rules show the line rather than describe it. `no_manual_table_schema`
asks a declaration **not to** hand-write a schema qualifier, which is safe advice for a
SQLModel table anywhere, so it travels. `table_models_use_base_table` asks a declaration
**to** inherit `BaseTable`, which a package outside the platform cannot do, so it does
not. Negative-versus-positive phrasing is a useful tell and not the rule;
`no_exception_text_in_responses` is phrased negatively and still stays behind, because a
worker has no response for a library's diagnostic string to reach.

**The four rules ADR 0136 widened travel, and a test says so by name.** Root kind is a
second dimension, and it is where 0136 could be undone without the diff looking like it:
classifying any of those four `APP_ROOT_ONLY` would re-exempt precisely the sibling
package 0136's own Context names as where a raw client and a bootstrap credential
actually live. `test_the_security_rules_widened_by_adr_0136_still_reach_every_root`
exists to make that a red build rather than a judgement call.

**The unmapped fallback is `EVERY_ROOT`, and the polarity is the decision.** A consumer
holding a newer harness than its pinned classification runs an unknown rule everywhere.
A rule that runs where it does not belong produces a false positive carrying a file, a
line and a fix; a rule that quietly stops running produces a green gate that proves
nothing, which is what took a security review to find. Fail towards the noisy one.

**One budget, shared.** The escape-hatch ratchet counts the markers of every scanned
root against one checked-in file. A repository argues about one number per exception,
and an opt-out cannot be relocated from the app into a sibling package to get out from
under its count. A per-root budget would have made moving the code the cheapest way to
lower a number.

**A marker that names a rule its root never runs is refused.** `#
arch-allow-list-routes-paginate` in a worker suppresses nothing. Left counted, it sits in
the budget reading like a governed exception while doing nothing at all — which is the
same false assurance a scoped-out rule produces, so it fails on its own line rather than
passing quietly.

**The project declares its companions once, and both entry points read it.**

```toml
[tool.terp.arch]
app_packages = ["control_plane"]   # more of the app; held to every rule
companions = ["engine"]            # ships beside it, unmounted
```

Two keys because there are two things to say. `app_packages` is *more of the
application* — code that participates in the Terp contract and is held to every rule,
exactly as `app/` is. `companions` ship alongside without being mounted. A control plane
is emphatically the first: it declares permissions and operations, so exempting it from
the rules about permissions and operations would be the wrong half of the wrong idea.
The template declares `control_plane` for every new app, and this repository's gate
scans the example app's, so the shape that reaches every application is covered by
default rather than by an upgrade note.

This is not ergonomics; it is what makes the shared budget safe. `terp verify` runs a
fixed `terp check` command that an app cannot add flags to (ADR 0106: the profile is open
at the app end, but a platform check is not rewritable). Had the declaration lived only
in the pytest call, an app adopting companion roots would count its companion's markers
in one run and not the other — and because the ratchet demands an exact match, the run
that missed them would read the difference as a *win to lock in* and fail. So an app that
did the right thing would break its own verify profile for having done it. One
declaration, read by `terp check` with no flag and spread into `assert_app_clean` by
`declared_roots()`, removes the failure mode instead of documenting it.
`--companion` remains for an ad-hoc companion scan and is a *union* with the
declaration: both
spellings say a root should be scanned, neither says another should not be.

**A declared directory that does not exist is an error.** A typo would otherwise scan
zero files, return zero violations from every rule, and report clean over a package
nobody checked — the failure mode of this whole area, reproduced in a config key.

**The report says what each root was held to.** `terp check --format json` grows a
`roots` array: package, kind, and that root's own evaluated-rule inventory. Top-level
`rules` stays the union, which for any run containing an app root is the whole registry,
so what a catalog consumer joins on is unchanged. The Terp Standard envelope
(`--format check-report`) gains nothing: `app-check-report.schema.json` is the standard's
shape and grows a field through the standard, not through this renderer. What the change
does buy is that the guide's honest caveat can be deleted rather than restated — a green
over a companion now names the rules it is green *about*.

## Consequences

**This adds no rule, which is why it is worth doing now.** ADR 0122 froze the catalog at
its breadth and redirected effort into making existing refusals legible and reachable.
This is that: eighty rules that already exist, reaching code they already applied to in
principle, with the scope written down instead of assumed. No catalog entry, no
`_AWAITING_SPEC_RELEASE`, no spec release, no pin bump.

**Recording root-kind applicability in the Standard is the natural follow-on, and is
deliberately not done here.** "Does this rule apply to a deployable that is not the app?"
is a stack-neutral property of a rule, and a JS checker facing a second package would
want the same answer — so it has a real claim on `catalog/schema.json` beside
`runtime.applicability`. It is deferred because folding a schema bump into this would
turn a contained framework change into the two-repo release sequence, and because the
classification should be lived with in one implementation before it is published as
normative.

**Adopting this will fail some repositories' gate the first time they declare a root,
and that is the point.** Rules arriving at once over a package that has never been
scanned will find things. They were violations the whole time; nothing was reporting
them. The fix is the one the platform always offers: move the code behind the seam, or
justify the exception with a marker and budget it. An existing app feels this on
`control_plane` before it feels it on any worker, because that is the package it already
has — which is also why the template ships the declaration rather than leaving it to be
discovered.

**A companion that serves the platform's own HTTP surface is an `APP`.** The kind
describes what the code *is*, not how many processes run it. A second FastAPI app built
on Terp is a second app root and should be scanned as one; `COMPANION` is for the
deployable that is not one.

**The bespoke test module does not disappear on its own.** A repository that hand-rolled
its missing rules still has them, and some of those genuinely say something no general
tool expresses — a dependency allowlist, a containment boundary particular to that
worker. The ones worth keeping are the ones that are not a weaker copy of a rule in
`RULE_ROOT_KINDS`, and telling the two apart is a review, not a migration script.
