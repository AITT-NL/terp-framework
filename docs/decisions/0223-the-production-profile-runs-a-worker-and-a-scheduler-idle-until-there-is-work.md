# 0223 — The production profile runs a worker and a scheduler, idle until there is work

- **Status:** Proposed on 2026-11-26. Held by `tests/architecture/test_prod_profile.py` (both
  services in the template's profile and the example's, the scheduler single, the heartbeat
  checks, the runtime-role overlay), by `test_deployment_generator.py` (the seed renders the
  template's profile byte for byte), by `test_cli_jobs.py` (the two commands idle where there is
  nothing to do and refuse where there is), by `test_cli_verify.py` (production-readiness names
  a missing service), and by the `prod-smoke` lane, which runs a scheduled job and an enqueued
  durable job in the example's production stack.
- **Date:** 2026-11-26.
- **Relates:** builds on [ADR 0181](0181-terp-supplies-the-inside-of-a-deployable.md) decision 1,
  which names the worker and the scheduler as processes of the shape Terp supplies, and on
  [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md) and
  [ADR 0191](0191-readiness-asks-the-stores-a-deployment-requires-and-a-worker-reports-a-heartbeat.md), whose generator and heartbeats
  render and probe them. Amends [ADR 0047](0047-scheduler-seam-and-schedule-catalog.md) and
  [ADR 0049](0049-scheduler-cli-entrypoint.md) (decision 8), and
  [ADR 0128](0128-the-gate-asks-whether-the-app-would-boot-in-production.md),
  whose production-readiness check gains a question no boot asks, and
  [ADR 0184](0184-a-deployment-declares-its-units.md); both status lines record it. For 0184: `terp verify --only deployment` still never fails on a schedule with no
  scheduler, and production-readiness now does when the project's own compose profile is the
  deployment.

## Context

The template's production profile ran four services: the database, the migration step, the
API and the web tier. Nothing in it ran `terp jobs worker` or `terp jobs scheduler`. An app that
declared a schedule, or wired the durable outbox and enqueued a job, deployed with a healthy
API and a green gate, and the work did not happen: the schedule never fired and the outbox
filled up. Integrations are mostly that kind of work (a scheduled sync, a token refresh, a
received webhook processed later, an outbound delivery and its retries, mail), so the gap was
found while mapping which integrations can be built as ordinary app code.

The only instruction was a sentence in `docs/DEPLOYMENT.md`: add those as extra services. Under
`"build": "own"` the production profile is a template-owned file, so a service added by hand
diverges from the template on every `copier update`. `require_durable_jobs` checks the queue,
not that anything drains it, and no check looked for the processes.

## Decision

1. **The template's production profile always runs a `worker` and a `scheduler`.** The seed
   `deployment.json` declares them as units, after the web tier: `worker` with role `worker` and
   `instances: "many"`, `scheduler` with role `scheduler` and `instances: "one"`, each depending
   on the database and the migration step. The generator renders them as it already renders the
   reference app's (ADR 0187): the backend image, `terp jobs worker --forever` and
   `terp jobs scheduler`, `.app.env` plus `.app.<unit>.env`, `init: true`,
   `restart: unless-stopped`, `depends_on` the database healthy and the migration completed,
   the container log rotation, and the heartbeat check of ADR 0191. The runtime-role overlay
   gives both the runtime role and the per-module schema layout the API has. `apps/example`
   runs the same two services by hand, since its profile is its own.
2. **Each idles where there is provably nothing to do.** `terp jobs worker --forever` in an app
   that does not install `terp-cap-outbox` keeps no outbox, so nothing could ever reach it: it
   says so in one log line, names what would give it work, keeps its heartbeat fresh and waits
   for the stop signal. `terp jobs scheduler` does the same in an app that declares no schedule
   and installs no scheduler engine, and in one whose schedules fire on Celery beat (the beat
   capability installed, APScheduler not): beat is that app's scheduler. Before, both exited, which under `restart: unless-stopped`
   is a restart loop, and which `docker compose up --wait` reads as a failed deploy.
3. **Where there is work, they stay loud.** A declared schedule with no engine installed still
   stops the scheduler with the message that names the package. A single drain (`terp jobs
   worker` without `--forever`) without the outbox still stops with its message: an operator who
   runs it by hand wants to know. "Not installed" means the capability's own module is missing;
   any other import error inside it, a missing dependency of an installed adapter included, is
   raised, not read as a reason to idle. An app on Celery that installs neither the outbox nor
   APScheduler keeps the template's worker and scheduler idle beside its own Celery worker and
   beat: decision 7 is what asks for those, and beat's ticks need a Celery worker to run them.
   With APScheduler installed as well, the template's scheduler fires beside beat and every tick
   fires twice: the database schedule ledger dedupes that only on the outbox queue, since a broker
   queue publishes before the ledger's compare-and-set. Run one scheduler.
4. **The template adds no dependency.** An app that wires the durable queue already imports
   `terp-cap-outbox`; one that declares a schedule installs `terp-cap-scheduler-apscheduler`.
   Installing both in every app would put the outbox's tables and a scheduler engine into apps
   that have no jobs.
5. **The files volume follows the work.** Under the files answer, the storage volume mounts on
   the worker and the scheduler as well as the API: a job that writes a file writes it where the
   API reads it, not into a container layer that the next restart discards.
6. **The scheduler is one; the worker scales.** The declaration says so (`instances`), and the
   profile names no fixed container, so `docker compose up --scale worker=N` works. Nothing
   locks the scheduler at runtime: with the durable schedule ledger a second instance loses the
   ledger's compare-and-set and enqueues nothing (ADR 0191); with any other trigger it would
   fire twice. Do not scale it.
7. **`terp verify --only production-readiness` names the missing service.** When the project
   carries `docker-compose.prod.yml` and its control plane declares work, the profile must run
   the process the installed engine needs: with `terp-cap-outbox`, a service running `terp jobs
   worker`; with the Celery jobs capability, a Celery worker (either, with both); with neither,
   jobs run inline in the process that enqueued them and no worker is asked for. A declared
   schedule needs `terp jobs scheduler` with APScheduler installed, or beat with the Celery beat
   capability installed and a Celery worker to run its ticks; `terp jobs scheduler` with neither engine fails, since it stops at start.
   A service counts only when a plain `docker compose up` runs it: not behind `profiles`, not
   scaled to zero, and a single drain that no restart policy (`restart:` or
   `deploy.restart_policy`) brings back is not a worker. A command counts wherever the profile writes it (a list, `uv run`, a shell loop); an
   image's `CMD` is not read, and a shell string that only mentions the words cannot be told
   apart (a residual), while a string Compose could not split counts as nothing. The failure
   names the service and the declared work, and leads with the remedy that turns it green for the
   engine installed: write the service with its command into the profile (installing the engine
   it needs first), re-render the template, or, under `"build": "generated"`, declare the unit
   and render. A worker is asked for only where a job is declared: an app that uses the outbox
   for events alone is not judged (a residual). Only `docker-compose.prod.yml` is
   read, as `deploy-safety` reads it, not the overrides `deployment.json` may list. A project with
   no compose profile is deployed some other way, and the check says it did not judge that half:
   which process triggers the work is then the deploy tool's business, as ADR 0184 has it. A
   profile that cannot be parsed fails, as `deploy-safety` fails on one.
8. **A declared schedule is fired by a scheduler, an external cron declares none.** The
   template's profile runs `terp jobs scheduler`; an app on Celery runs beat. A cron, a k8s
   CronJob or a timer outside the app calls `terp jobs run <job>` and declares no schedule:
   declared as well, each tick would fire twice once a scheduler runs beside it. This replaces
   the older reading, in ADR 0047, ADR 0049, ADR 0184 and the scheduling module, that an external
   cron is the default trigger of a declared schedule; their status lines record it.
9. **The runtime-role overlay may not name a service the profile lacks.** The overlay gives the
   worker and the scheduler the runtime role, so it names both. Compose refuses an overlay service
   the base profile does not define, and an app under `"build": "generated"` that takes the
   updated overlay before it has declared and rendered the two units would deploy nothing.
   Production-readiness fails on that mismatch whether or not the app declares work, and names
   the remedy: declare the units and render, or, under `"own"`, re-render or add the services.

## Consequences

- `copier update` brings the two services to every app whose build files are its own. Its
  `deployment.json` is the app's and is not rewritten, which is fine: under `"own"` the
  declaration is partial, and a service it does not name is not its business.
- An app under `"build": "generated"` renders its profile from its own declaration, so it gets
  the services when it declares the units, and must do so in the same change as the update that
  brings the new overlay (decision 9; the upgrade note gives the two units). `terp deployment
  adopt` reads a profile back into a declaration and cannot see `instances`, so an adopted worker
  is declared `"one"`, the default, until someone writes `"many"`.
- Every app runs two more containers. Idle, each is one Python process that has built the app
  and wakes on its poll interval to write a heartbeat; an app without jobs notices nothing else.
- A deploy tool that discovers the profile's services by the image they share with the API
  deploys these two as it deploys the API, with no change.
- The development compose does not gain them: `terp dev` and the workbench run the default
  in-process queue, where a job runs inside the request that enqueued it.

## Not done

- A runtime lock that keeps a second scheduler from starting. The ledger's compare-and-set
  makes a second durable scheduler harmless, and the declaration states the intent.
- A readiness signal for a queue nobody drains. Workers stay out of the API's readiness
  (`docs/DEPLOYMENT.md`); the heartbeat check is what a deploy waits on.

## Alternatives considered

- **Render the services only when jobs or schedules are declared** (a copier answer that adds
  them). Rejected: the silent state comes back at the moment someone adds a job and forgets the
  second step, which is the moment that matters; and it needs a new answer, conditional blocks in
  the seed and the profile, and their test machinery.
- **A check alone, with no services in the template.** Rejected: the check would send an
  `"own"` app to hand-edit a template-owned file, which then diverges on every `copier update`.
- **Install `terp-cli[jobs]` in every app** so the two commands always have their engines.
  Rejected for decision 4's reason.
