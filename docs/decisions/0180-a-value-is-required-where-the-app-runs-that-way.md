# 0180 — A value is required where the app runs that way, not everywhere

- **Status:** Accepted and implemented. A declaration in `environment.schema.json` may carry
  `"requiredIn"`, a non-empty list of distinct `ENVIRONMENT` values; `env-seams` judges it,
  `terp env check` holds the development loop's `.app.env` to what `local` needs, and the
  template declares `JOB_SYSTEM_ACTOR_ID` with it. Held by
  `tests/architecture/test_cli_env_seams.py` (the field, its refusals, its vocabulary pinned to
  `Settings.ENVIRONMENT`, and which names an environment needs) and
  `tests/architecture/test_cli_env_file.py` (`terp env check`).
- **Date:** 2026-10-10
- **Relates:** [ADR 0129](0129-the-job-actor-has-a-conventional-address.md) (the job actor's
  conventional address — this says where that address must hold a value),
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md) (the gate that
  reports a production refusal, satisfied by a declaration), Terp Studio's ADR 0085 (the
  reader on the deploy side, which landed first)

## Context

The framework already draws the line between a deployment and the development loop. Under
`ENVIRONMENT=production` a boot is refused over a missing job actor (ADR 0125, 0129); in the
development loop the same gap is a warning and the app runs. The manifest had no way to say so.
`required` is one array at the top of the file and means every environment, so an app with
background work had two choices: leave `JOB_SYSTEM_ACTOR_ID` optional and let a deployment go
out without it, or make it required and have it demanded in the development loop as well.

The second is what the template's guidance produced, and what it costs showed up in practice. A
workbench that asks for missing required values after a change asked a person for the id of a
service account in a database that only a deployment has. Nobody in the development loop can
produce that. The answer typed in its place was not a UUID, the settings object refused it, and
every backend service stopped at import.

## Decision

**A declaration says where it is required with `"requiredIn"`**: a non-empty list of distinct
values from `local`, `staging` and `production` — the values of `Settings.ENVIRONMENT`, kept equal
to them by a test, so the manifest names where an app runs in the same words the settings object
does. `required` keeps its meaning (every environment). A name in both is refused, because the
two answers to "where" cannot both be meant. An empty list, a word outside the vocabulary
(`"prod"`) or a repetition is refused too: a near miss would make the value required nowhere,
and a deployment would go out without it.

**The deploy side reads the same field.** Terp Studio runs the development loop as `local` and
every deployment as `production` — the template's two compose profiles — so it asks in the
development loop only for what `local` needs and refuses a deployment that lacks what
`production` needs. Studio's reader drops a property field it does not know, which is why its
support landed before this guidance: a manifest using the field never meets a current Studio
that ignores it.

**`terp env` is the development loop's command**, so `terp env check` reports an empty value as
missing only when `local` needs it.

**The template says it where it matters.** `JOB_SYSTEM_ACTOR_ID` is declared with
`"requiredIn": ["production"]`, and the guidance on `required` names the alternative.

## Consequences

- A value only a deployment needs is no longer demanded in the development loop, and a
  deployment still refuses to go out without it.
- Nothing changes for an existing manifest: without `requiredIn`, `required` reads as before. An
  app adopts the field by changing its own declaration; a template update re-renders the
  guidance, never the app's manifest.
- `staging` is in the vocabulary because `ENVIRONMENT` has it, not because a known deployment
  runs it; Terp Studio runs none, so a value required only there is asked for nowhere.

## Alternatives considered

- **A word of the deploy tool's own (`"requiredWhen": "deployed"`).** One more vocabulary for a
  distinction `ENVIRONMENT` already names, and one that only means something to one deploy tool.
- **Leave `JOB_SYSTEM_ACTOR_ID` out of `required` in the template.** Then a deployment is not
  refused before it starts, and the first anyone hears of the missing value is a production boot
  that fails.
- **A per-environment `required` array at the top of the file.** Puts the fact about one
  variable far from its declaration, and makes "is this variable required somewhere" a search.
