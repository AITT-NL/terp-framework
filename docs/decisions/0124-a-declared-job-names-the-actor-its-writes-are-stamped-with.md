# 0124 — A declared job names the actor its writes are stamped with

- **Status:** Accepted
- **Date:** 2026-09-08
- **Relates:** [ADR 0043](0043-jobs-seam-and-typed-enqueue.md) (the jobs seam whose system
  actor this constrains),
  [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the trail the stamp belongs to),
  [ADR 0109](0109-a-job-reaches-an-unowned-row-across-an-edge-not-a-directory.md) (what a
  job-declaring module may reach — this ADR is about what its writes are *labelled* with),
  [ADR 0115](0115-a-rate-limit-is-scoped-the-way-a-body-cap-already-is.md) (the
  `production_problems()` seam this reuses),
  [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (why this
  lands as a boot check and not as a new catalog rule).

---

## Context

The platform tells an application, in three separate places, that a job with no originating
user still produces attributed writes:

- `create_app`'s own reference documentation — the control plane's `job_system_actor_id` is
  "the stand-in actor a job runs as when no user originated it, so a job's writes are never
  silently unstamped".
- `terp.core.scheduling` repeats it for a schedule: a scheduled job "runs as the configured
  **system actor** and its writes stay audited + stamped, with no special-casing".
- `terp guide jobs` says it a third time, to the author most likely to rely on it.

The field that makes those sentences true is `ControlPlane.job_system_actor_id`, and it
defaults to `None`. It is the only member of that aggregate without a `default_factory` that
produces a working value — the eight beside it (`permissions`, `security`, `audit`, `events`,
`passwords`, `jobs`, `operations`, `schedules`) all build one. Nothing validated it:
`ControlPlane.validation_errors` boot-checks policy, event, job, permission and schedule
references, and a `ScheduleCatalog` full of entries with no system actor booted clean.
`create_app` then passed the `None` straight through to `configure_jobs`.

So an application could declare a schedule, satisfy every other boot check, and write rows
whose `created_by_id` answers **nobody**. That was found by running a schedule rather than by
testing one: a nightly tick submitted its work and the row landed with a null actor, in an
application where that column was the only durable answer to who told the platform to open a
connection to a production system.

**No unit test could have caught it, and that is the point.** A test asserts the row exists,
and an unattributed row exists. The failure is invisible to the suite, invisible at boot, and
only visible later, to whoever needs the trail — which is exactly when it cannot be
reconstructed. Two surfaces already *reported* the state and neither acted on it: `terp
inspect` emits `"job_system_actor": <bool>`, and `terp jobs` prints the actor only when one is
set.

## Decision

### 1. Production refuses to boot with unattributable background work

`ControlPlane.production_problems()` joins `SecurityConfig.production_problems()` and
`PasswordPolicy.production_problems()` on the `create_app` production path. It reports one
problem when the plane declares at least one job or schedule and carries no
`job_system_actor_id`, and `create_app` raises `BootError` on it.

The seam is deliberate. The `require_*` flags (`require_durable_jobs`,
`require_shared_cache_store`, `require_shared_throttle_store`) are the wrong shape here: each
of those guards a *backend choice* whose safe form costs infrastructure — a broker, a shared
cache — so an app has to opt in, and an app that never sets the flag is making a defensible
trade. A system actor costs a UUID. There is no production deployment that *wants*
unattributable job writes, so it belongs with the checks production applies whether or not it
was asked, not with the ones it has to remember.

### 2. Outside production the boot warns, and says what production does with the state

Development and test keep booting. A developer who has not wired a system principal yet
should not be blocked by one, and the in-process default runs jobs inline where the trail
matters least. But the row a local tick just wrote is unattributed either way and nothing else
in the system will ever mention it, so the boot logs a warning that names the field and states
the production behaviour — the shape the unshared-idempotency warning already uses for its
flag.

The warning is silent when an actor is set. A warning that cannot go quiet is noise, and the
test asserts both directions for that reason.

### 3. A reserved sentinel actor was the other candidate, and is worse

The obvious alternative was to default the field to a documented constant platform UUID, which
would have made the promise unconditional with no boot change and broken nothing. It was
rejected on the strength of a detail that first looked like an argument *for* it: the
actor-stamp columns are **FK-less by design**, so a constant would store perfectly well and
resolve to no principal anywhere in the system.

That converts "this row names no actor" into "this row names an actor that cannot be looked
up". The first is obvious to anyone reading the column and greppable as a null; the second
renders as a dead identifier in every view that resolves an actor, and looks like a data
problem in the app rather than a configuration one in the platform. It is the same defect made
harder to see, which is the failure mode this platform keeps finding in its own gates — a
check that is green while inert, a limit that looks like it applied.

### 4. The three sentences now state their condition

Each of the three places that made the promise unconditionally now says it is enforced rather
than assumed, and names the behaviour. That is not a substitute for the check — correcting the
documentation alone was the cheapest and worst of the available answers — but a promise that
is now conditional has to read as conditional, or the next author trusts the old sentence.

### 5. This is a boot check, not a new rule

ADR 0122 froze the catalog's breadth: a new rule needs a consumer outside the catalog. This
finding *has* one, so the bar is clear — but a rule is the wrong instrument regardless. The
missing actor is not something a module's source can be scanned for; it is a property of the
composition root's own configuration, which is what the boot path is for. The same reasoning
kept the throttle-store guard out of the catalog.

## Consequences

- **An existing production application that declares a job or a schedule and never set
  `job_system_actor_id` will refuse to boot after upgrading.** That is intended, and it is the
  only breaking change here. The fix is one field naming the app's own system principal; the
  refusal states it.
- An application that declares no background work is untouched, in every environment.
- Development and test behaviour is unchanged apart from one warning.
- The stamp is still the app's own principal. The platform does not invent one, so a row's
  provenance keeps resolving to something the app can explain.
- `terp inspect`'s `job_system_actor` boolean is now a leading indicator of a boot refusal
  rather than a fact with no consumer. Surfacing that in the inspect output itself is a
  legibility improvement of the kind ADR 0122 §3 asks for, and is not done here.
- **This should be revisited** if an application appears with a legitimate reason to run
  declared background work in production with no attributable actor. None is known, and the
  refusal names the field, so the cost of being wrong is one line in a composition root.
