# 0128 — The gate asks whether the app it just passed would boot in production

- **Status:** Accepted and implemented. `production-readiness` runs in all three verify
  profiles, reads the declared control plane's three environment-independent boot
  refusals, and fails on any of them; `tests/architecture/test_cli_verify.py` holds the
  verdicts and the profile membership.
- **Date:** 2026-09-09
- **Relates:** [ADR 0125](0125-a-declared-job-names-the-actor-its-writes-are-stamped-with.md)
  (the refusal that exposed the gap, and why a sentinel actor was refused),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern
  enforced, escapable by proof — and an audience that cannot evaluate a security
  trade-off for itself),
  [ADR 0111](0111-flexibility-is-bounded-by-legibility-not-by-capability.md) (properties,
  never topology — the line this check stays on the declaration side of),
  [ADR 0106](0106-the-verify-profile-is-open-at-the-app-end.md) (the profile's shape and
  what a check id means in the envelope)

## Context

Terp refuses a production boot in three states that are decided entirely by what an app
declares — no environment, no database, no request:

- a security config with CORS unset or wildcarded, or rate limiting off
  (`SecurityConfig.production_problems`);
- a password policy with the strength floor taken out (`PasswordPolicy.production_problems`);
- background work that names no actor to stamp its writes with
  (`ControlPlane.production_problems`, ADR 0125).

Outside production each of those logs a warning and keeps booting, and that asymmetry is
deliberate: a developer who has not wired a system principal yet should not be blocked by
one. What was missing is anything at all between the two behaviours. `terp verify
--profile full` — the merge bar, the thing CI runs, the thing an agent reads — never asked.
So an app could declare a job, never set `job_system_actor_id`, and carry an unqualified
green through review and into a deployment that refuses to start, with every surface
agreeing along the way because none of them had a question about it.

Reported from a full upgrade of an app with background work: `profile full is green` on a
tree whose production boot was already refused. The warning existed and went to stderr,
correctly, from a command run for a different purpose. The only reason it was noticed at all
was that someone read the release notes and then ran `terp jobs list` on a hunch.

The platform had already settled this argument against itself, one check earlier. The
comment above `platform-install` reads: *"`terp --version` already detects this and warns; a
warning inside a command nobody runs before shipping is not a control, so the verdict lands
here, where it can fail."* That is the same sentence about a different fact.

Two shapes were considered. A `warnings[]` array in the `terp_verify` envelope would let a
check pass while carrying a caveat — but it answers a narrower question than the one asked
(it makes the state *visible*, not *refused*), and it adds an envelope key with no reader in
this repository. A check makes the state a verdict, which the envelope already models: `ok`
goes false, the check is named, and text and JSON say the same thing without a new
vocabulary.

## Decision

**A new check, `production-readiness`, in every profile.** It resolves
`control_plane:control_plane` — the reference `terp jobs list`, `terp inspect control-plane`
and the template's own composition root already read — and reports each of the three
refusals above, prefixed by which half declared it. Any of them is exit 1.

**All three, not only the reported one.** Fixing the job-actor case alone would leave the
same class of defect in two other places, which is the trap `upgrade --check`'s own report
warns about one level up: *"a recipe that names only one is how the other goes stale."* They
are one code path and one message.

**Declarations only, and the audit refusal is deliberately excluded.** The fourth production
refusal — audit enabled with no durable sink — turns on `create_app(audit_sink=...)`, a
runtime argument this check cannot see. A check that pretended to cover it would be worse
than the honest gap, which is the same reasoning `deploy-safety` gives for implementing two
invariants instead of five.

**It reads the plane and never builds the app**, so it costs one module import, needs no
database, and can sit in `quick` beside `deploy-safety` — the earliest possible warning for
a fact that is otherwise learned on deployment day.

**A tree with no `control_plane/` package skips with a note**, the shape `routes-drift`
already uses for an unadopted seam: the platform's own checkout is such a tree. A package
that imports and yields something other than a `ControlPlane` is a red, because every other
Terp command reads that same reference — the app has adopted the pattern and the surface the
tooling depends on has stopped answering.

**The escape is the declaration itself.** There is no new marker and no budget entry. CORS
is excused by `CorsPolicy.disabled(reason=...)`, which is already the framework's escape
shape: explicit, greppable, and arriving in the diff that accepts the risk. Background work
is excused by naming an actor or by not declaring the job.

## Consequences

A newly scaffolded app is green: the template declares `CorsPolicy.disabled(reason=...)`,
takes the default password policy, and declares no jobs. Verified against the reference app
too, which declares a job and names its actor.

An existing app that declared background work without an actor turns red on the next gate
run instead of on its next production deploy. That is the point, and the failure names the
field and the fix.

One general gate arrived with this and is worth recording separately, because mutation
testing is what found it: a check declaring an in-process `runner` that the dispatch chain
does not handle used to fall through to the `else` branch, which shells the check's own
`command` — so the check re-invoked `terp verify --only <id>` in a child process running the
same code, and recursed. Nothing failed; the symptom would have been a gate that hangs.
`test_every_in_process_runner_is_dispatched` now reads the dispatch chain against the live
`PROFILES` table, and it catches the same mutation applied to a pre-existing runner.
