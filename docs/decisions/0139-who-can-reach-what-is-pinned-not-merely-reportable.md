# 0139 — Who can reach what is pinned, not merely reportable

- **Status:** Accepted and implemented. `terp inspect access --format surface` emits the
  authority baseline, the `authz-surface` verify check diffs the composed surface against
  a committed `authz-surface.json`, and `apps/example` commits one. Held by
  `tests/architecture/test_authz_surface.py`.
- **Date:** 2026-09-15
- **Relates:** [ADR 0121](0121-one-decision-one-function-the-access-graph-replays-the-guard.md)
  (the projection this reduces, and the reason it can be trusted),
  [ADR 0102](0102-every-route-declares-the-operation-it-performs.md) (the declaration the
  graph reads), [ADR 0011](0011-a-view-is-never-a-second-source-of-truth.md) (why this is
  a check over a view rather than a second model)

## Context

ADR 0121 established something unusual and valuable: the access graph does not *describe*
enforcement, it **replays** it. Every allowance in it is `terp.core.module_spec.decide`'s
own answer, computed by the same function the kernel guard runs, on the same inputs, in
the same order. The ADR was explicit about why — two copies of one authorization decision
is the shape whose drifting half "is the one an administrator is shown".

So the platform could always answer, exactly and truthfully, *who may reach what* for any
composed app. `terp inspect access --app app.main:build --format json` prints it.

What nothing did was **notice when the answer changed**.

Each of these is a one-line edit:

- a module's `Policy` moving from `Permission("connections.read")` to `Roles.VIEWER`;
- a `require_permission` dependency dropped from a route signature;
- a new endpoint added to a router whose module policy is `Policy.public_write`;
- a role's rank changed, which silently re-scores every floor at or above it.

Every one changes who can reach what. Every one leaves the architecture rules green, the
type checker green, and the test suite green — unless some test happened to exercise that
exact route with that exact persona. A persona suite is valuable and is not this: it
samples, and the endpoint added next week is by construction not in the sample.

The projection existed, the enforcement was correct, and the *change* went unreviewed.

## Decision

**The authority surface is a committed artifact.** `terp inspect access --format surface`
renders the access graph reduced to what is an authority claim — the role ladder, each
permission's floor, and per module its policy plus each endpoint's requirement, extra
grants and per-rung outcome — sorted at every level so the file is diffable. An app
commits it as `authz-surface.json`.

**The reduction is deliberate and narrow.** The graph carries a model's traits, the
reconciliation's `omitted_routes`, and whatever a future field adds; a baseline that
churned on those would be regenerated reflexively until nobody read the diff. What
survives is only what answers the question.

**The check reports changes in the vocabulary of the change**, not as a JSON diff: *this
route's requirement moved from X to Y*, *this endpoint is now reachable by ['viewer']*,
*this endpoint is NEW and nothing has reviewed what it requires*. A reviewer should be
able to approve or reject each line without reading the artifact.

**Adoption is opt-in; half-adoption is impossible.** With no committed baseline the check
skips with a note naming the command that writes one — the shape `api-docs-drift` settled
on, for the reason it settled on it: upgrading the framework must not turn an app's gate
red for a feature it never wired. Once the file is tracked, drift is red.

**Regenerating is not a fix.** The writer is a separate, explicit command and never a
`--fix` on the checker, because the baseline is a *review* artifact: the diff belongs in a
pull request where a person says yes. A `--fix` would convert the control into a
formality, and the failure message says so — "re-generate the baseline IN THE SAME CHANGE
so a reviewer sees the diff".

It sits in `full` as well as `release`, because a widening is a merge-bar question.

## Consequences

An app adopts with one command and one commit. Thereafter any change to its authorization
surface arrives as a reviewable diff attached to the change that caused it, which is the
only moment at which anyone has the context to judge it.

**The baseline will produce diffs that are not widenings** — an added endpoint at the
right tier, a renamed module. That is intended: the artifact records the surface, not
only the dangerous parts of it, because a check that tried to classify "dangerous" would
be a second authorization model, which is the thing ADR 0121 exists to prevent. The
review cost is one diff per authority change, and authority changes should not be
frequent.

**It does not replace a persona suite.** This answers "did the declared surface change";
a persona test answers "does a real caller actually get refused". The second is a
stronger claim about fewer routes, and the two are complementary — `apps/example` keeps
both.

The example app adopts it, so the artifact is exercised by the suite rather than
described by it: a change to the example's authority surface that lands without
regenerating the baseline fails `test_the_example_app_baseline_matches_its_composed_surface`.
