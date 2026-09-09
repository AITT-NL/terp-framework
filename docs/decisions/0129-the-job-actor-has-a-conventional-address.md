# 0129 — The job actor has a conventional address, and the requirement is unchanged

- **Status:** Accepted and implemented. `Settings.JOB_SYSTEM_ACTOR_ID` is a typed
  `uuid.UUID | None`, `create_app` resolves an unset `ControlPlane.job_system_actor_id`
  from it before the production refusal is read, and an explicit field still wins.
  Held by `tests/architecture/test_jobs.py`.
- **Date:** 2026-09-09
- **Relates:** [ADR 0125](0125-a-declared-job-names-the-actor-its-writes-are-stamped-with.md)
  (the requirement, and why a sentinel default was refused — this amends its delivery,
  not its verdict),
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md) (the gate
  that reports the refusal, and why a declaration satisfies it),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern
  enforced; the audience cannot be asked to hand-roll a security-relevant parse),
  [ADR 0088](0088-service-principal-credentials.md) (the sanctioned path has to be the
  easier one)

## Context

ADR 0125 established that a declared job must name the actor its writes are stamped
with, and refused a platform-wide sentinel actor. That refusal was right and is not
revisited here: the column is FK-less, so a constant would store cleanly and resolve to
no principal anywhere — "no actor" turned into "an actor nobody can look up", which is
the same defect wearing a value.

But a decision about the *default* left the *delivery* unspecified, and the delivery is
not a free choice. The id belongs to a service principal in a particular database, and
one image runs against several — so it cannot be a source constant. Every app that
declared a job therefore wrote the same block: read a variable, parse a UUID, raise
something useful when it is absent or malformed, thread the result into the control
plane. Reported from an upgrade as roughly thirty lines of it, and the framework's own
reference app sidesteps the question with a fixed constant precisely because it has no
principal to point at — with a comment explaining that a real deployment must do
something else.

That is the shape ADR 0088 warns about from the other direction: when the sanctioned
path is the laborious one, the requirement gets satisfied badly or not at all. And the
audience this platform is built for cannot be handed a UUID parse and an error path as
the price of declaring a nightly job.

## Decision

**`JOB_SYSTEM_ACTOR_ID` on the settings object, typed.** `uuid.UUID | None`, defaulting
to `None`. Pydantic parses and refuses it, so the malformed-id error lives in one place
instead of in every app, and no app receives a string it has to validate.

**`create_app` resolves an unset field from it, before the refusal is read.** The order
is the whole point: resolving afterwards would refuse a boot over a value the process
already had. An explicit `ControlPlane(job_system_actor_id=...)` wins, because an app
that resolves its principal some other way must keep saying so.

**The requirement does not move.** Unset in both places is exactly what it was:
`production_problems` reports it, production refuses the boot, development warns and
keeps going. This adds an address, not an exemption — and it is not the sentinel ADR
0125 refused, because a variable nobody set supplies nothing.

**A declaration satisfies the gate; a value is not required there.** ADR 0128's check
reads the app's `environment.schema.json` and accepts `JOB_SYSTEM_ACTOR_ID` being
declared, because a production principal's id is the last thing a gate's environment
would hold. The declaration is a promise with a gate already behind it: `env-seams`
refuses a declared variable the deployment does not deliver, and `terp env file` renders
it. An app that declares nothing is still red.

## Consequences

An app with background work now has one line to write instead of a block, and the line
is a declaration rather than code.

The variable is a UUID, and `environment.schema.json` has no `format: "uuid"` or
`pattern` vocabulary — a related gap, reported alongside this one. It stays unfixed on
purpose: the value is validated where it is read, by the typed field above, and adding a
second validation site in the manifest would be two answers to one question. The
manifest's job is to declare that a variable exists and must be delivered.

`Settings` grows a field that most apps leave unset, which is the same shape every other
opt-in setting there already has.
