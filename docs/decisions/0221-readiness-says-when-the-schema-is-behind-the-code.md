# 0221 — Readiness says when the schema is behind the code

- **Status:** Proposed on 2026-11-24. Held by `tests/architecture/test_readiness_schema.py`
  (what readiness answers, how often it asks, the boot guard's pass, the body of an app that
  does not ask, the migration guard itself end to end, and the template's and the reference
  app's composition roots, run in development and in production) and
  `tests/architecture/test_readiness.py` (two probes arriving together run one check).
- **Date:** 2026-11-24.
- **Relates:** amends [ADR 0024](0024-health-endpoints-and-pool-config.md) decision 1 and
  [ADR 0191](0191-readiness-asks-the-stores-a-deployment-requires-and-a-worker-reports-a-heartbeat.md)
  (what readiness asks), and the consequence of
  [ADR 0185](0185-a-release-declares-the-schema-window-it-accepts.md) that the window adds no
  readiness signal: the boot guard and its window are reused unchanged, and readiness now asks
  them where the boot does not. Studio's preview reads `/health/ready`, so this changes its
  gate, as the managed-deployment decision log's S4-13 says any readiness change does.

## Context

Readiness asks whether the database answers `SELECT 1`, and whether every shared store a
`require_shared_*` made mandatory answers its ping. A database behind the code answers
`SELECT 1` like any other. So an app serving a schema its code has outgrown said "ready", and
its first query against a missing table or column failed: a bare 500, and nothing anywhere
naming the migration that had not run.

The boot guard, `assert_migrations_current`, refuses exactly that schema, but the template
arms it in production only (ADR 0185). Everywhere else the app starts on whatever schema it
finds, on the assumption the template's comment stated: "Development keeps auto-applying
migrations for you". It does not, quite. The development stack's `migrate` one-shot runs when
the stack comes up, and again only when a `uv.lock` change rebuilds the image under watch. A
running stack whose code gains a migration (a re-rendered template, a capability upgraded in
place, a module that grew a revision) keeps serving the old schema.

Friction reported from upgrading an app across many releases: after the upgrade, the running
development stack had not applied the new migrations. Sign-in returned a bare 500, while the
readiness check the development workbench reads kept saying "ready". The only way to find the
cause was to read the API's logs.

## Decision

1. **`create_app(migration_readiness=...)` puts the boot guard's question in readiness.** Given
   the process engine, the callable raises while the schema is behind the code, and
   `/health/ready` answers 503 with the check `migrations` as `error` until it passes. It is
   asked like a mandatory store: on a thread of its own, within the readiness bound, never twice
   at once. That last held only once a thread had taken the probe up, so probes arriving
   together could each run it; an ask now claims its store before it waits for a thread, which
   holds every store to the same words (ADR 0191). A check that fails is logged with its own message, which for the guard names the
   packages behind and `terp migrate upgrade`. The public body says only `error`, as it does
   for a store.
2. **The check is the boot guard's, not a second definition of "current".** The template passes
   `terp.migrations.assert_migrations_current`, so a database ahead of the code inside its
   schema window (ADR 0185) is as ready here as it is at boot, and one outside it, or missing a
   module's history, is as not-ready as the boot is refused.
3. **Asked until it passes once, then never again in the process.** A process's migrations are
   fixed for its life, and a schema does not fall behind by itself. A probe every few seconds
   therefore costs nothing once the schema has caught up, which on a stack whose `migrate` step
   ran first is the first probe.
4. **The boot guard's pass counts.** Passing the very object given as `migration_check` tells
   readiness the boot already ran it: an instance that started on a current schema never asks
   again. The template passes one object to both seams, so a production instance, where the
   boot guard runs and refuses a behind schema, behaves exactly as it did before: no new
   check is run, and the body gains only `"migrations": "ok"`.
5. **An app that does not ask has the body it had.** The seam is opt-in, like
   `migration_check`, because the kernel never imports the migration subsystem.
6. **The template wires it everywhere.** `migration_check` stays production-only;
   `migration_readiness` is passed in every environment. The reference app's composition root
   carries the same wiring.

## Consequences

- **A development stack that has not migrated says so.** The workbench's readiness path is
  `/health/ready`, so a stack whose code gained a migration reads as not ready, with
  `migrations: error`, instead of ready-and-failing. Applying the migrations turns it ready
  within one probe, with no restart.
- **Production is unchanged, and so is every environment a release is deployed to.** The
  boot guard runs and its pass is the readiness answer, so no probe runs a migration check,
  the timing of readiness is what it was, and only the body gains `"migrations": "ok"`. A
  generated deployment gives every backend unit `ENVIRONMENT=production`, Test environments
  included, so the same holds wherever a runner deploys: its `migrate` step runs before
  `start`, a previous release starts again only on a database its own check accepts, a
  restore checks the database before `start`, and no drill boots the app. Every reader of
  readiness the managed deployment has or plans reads the status code alone.
- **Studio's preview gate changes, and Studio reads the check by name.** The preview mounts
  the app only once `/health/ready` answers 2xx, so a running development stack whose code
  gains a migration drops back to waiting until the migration is applied, instead of serving
  pages whose queries fail; while the gate stays red it keeps waiting, where it used to serve
  every route the schema change did not touch. Studio counts the wait as one on migrations
  only when `migrations` is the one failing check (a database it cannot reach fails it too),
  and says who ends it. Where it holds the migration for the project's own stack (an agent turn
  in the project's own checkout that changed a path under `migrations/`, or a publication that
  carried one), it says it applies them once the check is green, and does, with no restart.
  Anywhere else it says no migration waits in Studio and that a new start runs the app's
  migrations, and offers that start among its repairs: a conversation's own stack, which
  migrates at its next start and never while it runs (Studio ADR 0067, isolation being the
  default); a pull that brought a migration; a database ahead of the code outside its window.
  The stall is measured as before, so a check that stays red still reaches the repairs. A stack
  that comes up migrates first and is unaffected. The change reaches an app with the template's
  `app/main.py`, at its next re-render.
- **A database ahead of the code outside its window is not ready either.** That is the
  database the boot guard refuses: an applied revision the code does not define and the
  migration record cannot place, as after switching a development checkout to a branch that
  lacks a migration the database already ran. It used to read as ready.
- **No healthcheck waits on readiness.** Every Compose healthcheck of an API unit, in the
  template's profiles and the generator's, asks the liveness path, and the `migrate` one-shot
  waits only for the database. So a stack whose readiness waits on its migrations cannot wait
  on itself.
- **Outside production, the first probe after a start asks the guard once.** On a stack whose
  migrations ran before the API started, that probe passes; if reading every history takes
  longer than the readiness bound, the probes in between answer 503 until it finishes, and
  then 200.
- **A schema that falls behind under a running process is not noticed.** Only a downgrade or
  a restore of an older backup can do that, and the boot guard does not notice it either. A
  restart asks again.
- **A store's probe is claimed before it is dispatched.** The bound on each store (ADR 0191)
  marked a probe as running only once its thread started, so probes arriving together could
  each start one; an ask now claims the store first, and gives the claim back itself if it
  gives up before any thread took the probe up. Nothing a store answers changes.
- **`create_app`'s module made room for the seam.** The two production notices about
  per-worker stores move, unchanged, into `terp.core._store_warnings`, so `app.py` shrinks
  (2281 to 2234 lines in `OVERSIZED.json`).

## Not done

- **Nothing applies the migrations.** Readiness reports; it does not migrate. Running the
  `migrate` step is still the development stack's, the deploy tool's, or the developer's.
- **The public body does not name the packages behind.** `/health/ready` is unauthenticated,
  and the log line beside it already names them, as a store's failure is named in the log and
  not in the body.
- **Studio does not migrate a stack it holds no migration for.** A conversation's own stack, a
  pull, and a database ahead of the code wait for a new start, which the preview names. A
  capability's migration that arrives with a `uv.lock` change is applied where the stack runs
  under Compose watch, whose rebuild on the lock re-runs `migrate`; a stack run without watch
  applies it when it is next brought up.
- **The check's name is not a shared contract yet.** Studio reads `migrations` by name from
  the readiness body, which no terp-spec contract defines: each side keeps its own copy of the
  name, and a rename on one side turns Studio's named wait back into a plain one.
- **The runner's planned `readiness` event carries no check names yet.** Whether it should
  report `migrations` by name is the runner design's question; nothing here needs it to.

## Alternatives considered

- **Arm the boot guard in development too.** The API would refuse to start on a behind schema,
  so the stack would show a crashed API and a traceback in its log instead of a readiness
  answer, and every route, including the ones the schema change does not touch, would be down
  until someone migrated. Readiness keeps the process up and says what is wrong.
- **A readiness check of its own that compares heads.** A second definition of "current" would
  drift from the guard's, and the first case it would get wrong is the one ADR 0185 exists for:
  a database ahead of the code inside its window, where a rollback has to stay ready.
- **Ask on every probe.** Reading every package's history and its version table every few
  seconds buys nothing a process can observe: its code cannot gain a migration without a
  restart.
- **Register the check with `register_mandatory_store` from the composition root.** That
  registry is a capability's, made once at import; an app that builds itself twice, as every
  test does, would register a second, different probe under one name, which the registry
  refuses.
