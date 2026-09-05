# 0116 — A rule may run ahead of its published catalog entry, for one release

- **Status:** Accepted
- **Date:** 2026-09-05
- **Relates:** [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md) (the spec is a pinned
  package, which is what makes "the standard" and "the installed catalog" two different
  things),
  [ADR 0080](0080-terp-standard-rule-catalog-and-violation-corpus.md) (the catalog/implementation parity
  contract this narrows),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  enforced, escapable by proof — this is the escape, and the proof is that the entry exists
  in the standard and the list empties at release)

---

## Context

Adding a rule to Terp means changing two repositories, and until now the two changes could
not both be correct at the same time.

`test_backend_catalog_matches_the_rule_registry` compares the rules this repository ships
against the **installed** catalog — the pinned, published `terp-spec` release — and asserts
both directions are empty. A rule with no catalog entry is refused, and a catalog entry with
no rule is refused.

terp-spec's `certify-against-reference` job runs that same test, from **this repository's
default branch**, against the spec branch's unreleased catalog. It deletes the
`terp-spec==` pin before resolving, deliberately: the pin may already name the version the
spec branch is heading towards. So what it certifies is what `main` *implements*.

Put together, those two are unsatisfiable for a new rule:

- terp-spec cannot certify — and therefore cannot release — until the rule is on this
  repository's `main`.
- While the rule is on `main` and its catalog entry is unpublished, `main` fails its own
  parity test against the catalog it has installed.

There is no ordering that avoids it. Landing the framework first turns `main` red; landing
the spec first turns certification red and needs an override on a protected branch. The
window is not brief either: it lasts until the spec release is approved and published, and
that release parks twice for a human reviewer.

The cost had been paid quietly before, one rule at a time. It became visible when three
rules were added in one session and the sequence had to be written down.

## Decision

**A rule may be implemented while its catalog entry is unreleased, if it is listed in
`_AWAITING_SPEC_RELEASE`, and a framework release may not be cut while that list is
non-empty.**

Three assertions carry it, and each refuses a different way of going wrong.

**Parity narrows from "empty" to "a subset of the allowance".** A rule missing from the
installed catalog is still refused unless it is listed by name. The other direction — a
catalog entry with no rule — is untouched and still absolute: the standard may not describe
something the reference implementation does not do.

**The allowance may not rot.** Every listed name must be a rule this repository actually
implements, so a rename or a deletion cannot leave a permanent hole behind a dead name. And
a listed rule whose entry the installed catalog now carries is a failure, not a no-op: the
release landed, the window closed, and leaving the name listed would keep an allowance open
past the thing it was opened for.

**The window closes at the release.** `test_no_rule_awaits_a_spec_release` refuses to cut a
framework release while the list is non-empty. That is what makes this an allowance rather
than a loophole: a rule may outrun its published entry across a merge and a publish, and may
not outrun it into a release. Shipping an enforced rule that no published catalog documents
is precisely the state the parity contract exists to prevent.

That one assertion is conditional on a tag being built, and the condition is the decision
rather than an escape. Asserting it on every run would fail every ordinary build for the
whole length of the window the allowance exists to permit — the gate would refuse the state
it was written to allow, which is how the deadlock started. The shape is the one this
codebase already uses for `production_problems`, consulted only under
`ENVIRONMENT == "production"`: a real observable state, not a switch anyone can leave off.
The release workflow runs the full gate at the tag, and `test_release_workflow` holds it to
that, so the assertion is reachable exactly when it decides something.

During certification the parity assertion is trivially satisfied, because the catalog under
test already contains the rule. The allowance is invisible to the job it exists to unblock,
which is the sign it is in the right place.

## Consequences

**The sequence for adding a rule stops requiring anyone to be red.** Land the catalog entry
and corpus in terp-spec; land the rule here with its name in the list; terp-spec certifies
against a `main` that carries it and releases; bump the pin here and empty the list. Every
step is a green merge.

**The list is the record.** A non-empty `_AWAITING_SPEC_RELEASE` on `main` says, in one
place and in the diff, that a spec release is in flight and which rules are waiting on it.
That is strictly more legible than the previous answer, which was a red test and a comment
in a pull request.

**It is one more shrink-only list**, alongside `corpus/PENDING.json`,
`corpus/RESIDUALS.json` and the escape-hatch budget. That is deliberate: the pattern is the
repository's own, and a reader who understands one understands this.

## Alternatives considered and not taken

**Override the protected branch each time.** The obvious move, and what the runbook would
otherwise have to teach. It normalises merging past a required check on a
public repository, and it does not actually remove the red window — it only moves which
branch is red. A procedure whose first step is "bypass the guard" is a guard that will be
bypassed for other reasons later.

**Loosen the parity test permanently to a subset check.** One line, and it removes the
protection entirely: a rule could then ship uncatalogued for ever, which is the exact
failure ADR 0080 extracted the catalog to prevent. The list is the difference between an
exception with a name and an exception with none.

**Have certification test a branch instead of `main`.** It would let the framework hold the
rule off `main` until the release. But certifying against a branch certifies against
something nobody is running; the job's own comment says it tracks the default branch
deliberately, so that a framework change breaking parity surfaces there rather than at
release time. Weakening that to solve a scheduling problem trades a real guarantee for a
convenience.
