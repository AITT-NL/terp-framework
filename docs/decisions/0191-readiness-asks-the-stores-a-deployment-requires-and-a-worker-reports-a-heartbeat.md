# 0191 — Readiness asks the stores a deployment requires, a worker and a scheduler report a heartbeat, and a schedule says what a missed tick becomes

- **Status:** Accepted. Built in 0.35.0. Held by `tests/architecture/test_readiness.py`,
  `test_readiness_postgres.py` (the PostgreSQL lane), `test_realtime.py`,
  `test_schedule_misfire.py`, `test_scheduler_adapters.py`, `test_worker_lifecycle.py`,
  `test_worker_heartbeat.py`, `test_cli_jobs.py`, `test_jobs_celery.py`,
  `test_deployment_generator.py` and `test_reference_app.py`. The heartbeat checks and the
  database half of readiness were measured against a real stack (*How it was built*).
- **Date:** 2026-10-22
- **Relates:** amends [ADR 0024](0024-health-endpoints-and-pool-config.md) decision 1 (what
  readiness asks); amends [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  decision 5 (a worker and a scheduler had no check) and settles its open item on their health;
  amends [ADR 0045](0045-durable-outbox.md) (how the worker stops),
  [ADR 0046](0046-first-engine-adapter-celery-jobqueue.md) (when Celery acknowledges a job),
  [ADR 0047](0047-scheduler-seam-and-schedule-catalog.md),
  [ADR 0048](0048-scheduler-engine-adapters.md) and
  [ADR 0049](0049-scheduler-cli-entrypoint.md) (what a schedule declares, and what a scheduler
  remembers). Builds on [ADR 0036](0036-distributed-throttle-store.md) and
  [ADR 0078](0078-redis-backed-shared-stores.md) (the shared stores and their boot guards) and
  [ADR 0176](0176-a-realtime-publish-reaches-every-process-that-serves-the-channel.md) (the
  shared broker).

---

## Context

A deployment that runs a worker, a scheduler and a shared store asks four questions of the
app and got a true answer to none of them.

**Is this instance ready?** Readiness asked the database alone. A deployment that set
`require_shared_throttle_store=True` (or the cache, idempotency or broker equivalent) had
promised that the store is shared, and the boot guard held that promise, but once the store
went away the instance still reported ready while every request that needed the store failed.
Worse, the rate limiter fails closed on a store error, so every request was answered 429,
`/health/live` and `/health/ready` included: liveness failed on a store outage, which ADR 0024
says it must never do, and readiness answered with a status that names no dependency.

**Is the worker alive?** ADR 0187 decision 5 rendered a worker and a scheduler with no check,
because nothing honest existed: they serve no HTTP, an inherited HTTP probe turned them
unhealthy, and a disabled one made `docker compose up --wait` refuse. So a worker stuck in a
job that never returns was exactly as healthy as one draining the outbox.

**What happens to the job in flight when the worker stops?** `terp jobs worker --forever` ended
on SIGTERM only after draining the outbox empty, claiming batch after batch on the way, so a
stop grace could expire with a whole batch leased to a process about to die. A killed worker's
job relied on its lease lapsing, which nothing proved. The Celery task was registered with
Celery's default, acknowledgement on receipt, so a Celery worker killed mid-job took the job
with it: acknowledged, never finished, never redelivered.

**What happens to a tick that falls due during a deploy?** The scheduler is a process, and a
deploy stops it. The APScheduler adapter registered its cron jobs in memory, Celery beat keeps
its state in a file the next container may not have, and `ScheduleDefinition` had nothing to
say about lateness. A cron time that passed while no scheduler ran left no trace at all.

## Decision

**1. Readiness is the database and every shared store this deployment made mandatory.**

`GET /health/ready` keeps ADR 0024's `SELECT 1` through `SessionDep`, unchanged, and adds one
check per store a `require_shared_*` made mandatory: `throttle_store`, `cache_store` and
`idempotency_store` from `create_app`'s own arguments, and `realtime_broker` while
`configure_realtime(require_shared_broker=True)` stands. 200 when every check passes, 503
otherwise, each check named `ok` or `error` in `checks`. A store that is wired but not required
is not asked: requiring it is the deployment's statement that it cannot serve without it. The
bound its tests hold it to: 503 within 30 seconds of losing the database or a mandatory store,
and 200 within 30 seconds of its return.

- **How a store is asked.** Each store port (`ThrottleStore`, `CacheStore`, `IdempotencyStore`,
  `RealtimeBroker`) gains `ping()`: raise when the backend cannot be reached. The per-process
  defaults keep the port's no-op, because they live in the process that asks. `terp-cap-redis`'
  stores and broker answer with a Redis `PING`. A required shared store whose type does not
  override `ping` **refuses the boot** (the broker: refused under the promise), naming the fix:
  readiness could only report such a store reachable with a check that cannot fail.
- **Bounded, and never asked twice at once.** The stores are asked side by side, each on a
  worker thread, within 2 seconds (`READINESS_PROBE_TIMEOUT_SECONDS`). A probe that does not
  answer is abandoned and reported `error`, and until it returns that store is answered `error`
  at once, without a new thread: a store that accepts connections and never answers turns
  readiness 503 within the bound, and cannot pile up a thread per probe while it hangs. The
  database is asked as before, on the request's own session and thread, whose connection is
  given back before the stores are asked.
- **The rate limiter does not hide it.** While the throttle store itself cannot answer, a
  request to `/health` is let through instead of refused as rate-limited. Every other path still
  fails closed, and while the store answers `/health` is counted like any path.
- **A capability's store** registers with `register_mandatory_store(name, resolve)`, where
  *resolve* returns the store's probe while the capability holds it mandatory and `None`
  otherwise, so the promise and the check are one fact. The realtime capability is the first.
- **Workers, schedulers and the outbox backlog stay out**, as ADR 0024 and the health detail
  surface already argued: an undrained queue is a reason to page someone, and failing readiness
  on it would turn a delivery problem into an outage.

**2. A worker and a scheduler report a heartbeat, a file in their own container.**

`terp jobs worker --forever` and `terp jobs scheduler` write `terp-<role>.heartbeat` (`worker`
or `scheduler`) in the process's temporary directory, which in a container is the container's
own, so the file is per unit by construction. It is one JSON object, replaced atomically:
`role`, `pid`, `at` (seconds since the epoch), `stale_after` (seconds) and `beats`.

- **Written by the loop it vouches for.** The worker beats before each claim, after each job
  it finishes and between drains, so an idle worker beats every `--poll-seconds` and a worker
  stuck in one job stops beating. The scheduler beats from an interval job on its own engine
  every 10 seconds, so a scheduler whose engine stopped dispatching stops beating. A thread
  that beats on its own would prove only that the process exists, which the container state
  already says.
- **Its bound is the writer's.** The worker's is `max(--lease-seconds, --poll-seconds)` plus a
  30-second grace (60 s with the defaults): a job that outlives its lease is delivered again to
  another worker anyway, so the lease is the longest a healthy job may hold the loop, and a
  worker given a longer lease is given a longer bound with it. The scheduler's is three missed
  beats plus the grace, 60 s. A stuck process cannot move its own deadline.
- **Removed** when the process starts and when it stops, so a restarted container is not called
  healthy by the file its previous run left. A beat that cannot be written is logged once and the
  work goes on; the check, finding no fresh heartbeat, then says what is true.
- **What reads it.** The container's healthcheck (decision 3), with the standard library alone:
  no HTTP, no database, no import of the app. A deploy tool reads the same answer per unit
  from the container: its health status, and the age from the last probe's output (`docker
  inspect`, `.State.Health.Log`), or by running the probe in the container. That is a per-unit
  reading, there whether or not the API is up.
- **Considered and rejected:** a database row per worker (it needs each process mapped to its
  unit, and a worker whose database is down could not report at all); an HTTP endpoint on the
  worker (a server in a process that serves nothing, and a port); `/health/detail` (the API's
  container cannot see the worker's, and the outbox backlog's `oldest_due_age_seconds`, already
  there, stays the cross-process signal that work drains).

**3. The generator checks a unit whose command writes a heartbeat** (amends ADR 0187 decision 5).

A unit whose command is `terp jobs worker ... --forever` or `terp jobs scheduler ...`, declared
or the role's default and under any role, gets a healthcheck: `["CMD", "python", "-c",
HEARTBEAT_PROBE, "<role>"]`, every 10 s, timeout 5 s, 3 retries, a 30 s start period. The probe
is fixed text with the role as its one argument; it prints `{"heartbeat", "age_seconds",
"stale_after_seconds"}` as one line and fails when the heartbeat is older than its own
`stale_after`, missing, or unreadable. A unit that waits for such a unit waits for
`service_healthy`. A single drain, a companion or any other command writes no heartbeat and
keeps no check. The backend image still carries no `HEALTHCHECK`, and the template's seed has
no worker, so the template's files do not change; five golden samples and the reference app's
production profile do.

**4. A stop finishes or gives back the work; a kill's work comes back.**

- The outbox worker takes a stop event: once set it claims nothing more, the job running
  finishes, and the rest of its batch is **released** (lease cleared, attempts untouched,
  `DrainResult.released`), so another worker takes it at once instead of after
  `lease_seconds`. `terp jobs worker --forever` sets it on SIGTERM and SIGINT.
- `terp jobs scheduler` shuts its engine down on SIGTERM or SIGINT, once however many signals
  arrive, letting the ticks in flight finish.
- A worker killed before it could do either (a stop grace that ran out, an out-of-memory kill,
  a host that died) loses nothing: its rows are reclaimed once their lease lapses and run again.
  Delivery stays at least once, so a handler must tolerate running twice.
- The Celery task is registered with `acks_late=True` and `reject_on_worker_lost=True`: the
  broker forgets a message only after the job returned or raised, and a pool process lost under
  it hands the message back. Pair it with `worker_prefetch_multiplier=1`, and on Redis a
  `visibility_timeout` above the longest job, which is how long a dead worker's message waits.

**5. A schedule declares what a missed tick becomes.**

`ScheduleDefinition` takes a required keyword `misfire=`: `Misfire.RUN_ONCE` runs the missed tick
once, late, as soon as a scheduler is back, and `Misfire.SKIP` records it skipped and waits for
the next cron time. A slot settled within a minute of its cron time (`ON_TIME_SECONDS`, the
resolution of a five-field cron) is on time whatever the policy; every slot of one gap is folded
into the latest, so a scheduler down for a day runs an hourly job once, not twenty-four times.
There is no default, for the reason a reference's `on_delete` has none
([ADR 0133](0133-a-reference-declares-what-a-delete-of-its-target-does.md)): a default reads in the
source exactly like a choice, and only the author of the work knows whether it makes sense late.
The leases and sync capabilities' schedule helpers run a missed cycle once, and say so.

**6. A ledger remembers each schedule's last settled slot, and the durable one is the outbox's.**

The kernel's `ScheduleLedger` port holds, per schedule, the last slot settled and what became of
it (`fired`, `late`, `skipped`, or `baseline`: the moment the ledger first saw the schedule,
with nothing owed before it), and a counter its `settle` compares and sets.
`settle_schedule(session, schedule, latest_slot=..., now=...)` is the one decision both adapters
make, at start and on every cron time alike: the ledger's last slot `L`, the adapter's answer to
"the latest cron time in `(L, now]`", and now. The kernel parses no cron; the adapter's engine
does.

- `InMemoryScheduleLedger` is the default and forgets on restart, so a scheduler on it never sees
  a gap. `terp jobs scheduler` names that in its log.
- `terp-cap-outbox` ships `DatabaseScheduleLedger` over a new `outbox_schedule_fire` table (one
  revision in the outbox's history). Its `settle` is one write unit: the outbox queue's append
  joins it, the record moves by compare-and-set, and one commit lands both, so a crash leaves both
  or neither. A second scheduler that read the same record loses the compare-and-set and rolls its
  own outbox row back. Under a broker queue the job is published before the record commits.
- `create_app(schedule_ledger=..., require_durable_schedules=...)` wires it and, when required,
  refuses a ledger that is not marked durable.
- The APScheduler adapter settles every schedule on `start`, before the engine runs, and tells
  APScheduler to run a late tick rather than drop it after its one-second grace, so the policy
  decides whether the scheduler was down or merely slow. The Celery-beat adapter's tick settles
  through the ledger, so a tick beat fires late on start is the misfire it is, and
  `catch_up()`, called from beat's `beat_init`, settles a gap beat never fires for.
- *Considered and rejected:* an APScheduler job store in the app's database (it pickles the
  job's callable, creates its table outside any migration history, and serves one engine); a
  distribution of its own for one table; the ledger in the scheduler adapter (it would serve
  one engine, and the atomicity with the outbox row would be lost).

## Consequences

- Readiness turns 503 within seconds of losing a mandatory store and 200 within a second of its
  return, against a store that really goes away (decision 1's tests, *How it was built*), and the
  database half runs in the PostgreSQL lane.
- A worker or a scheduler that stops making progress turns its container unhealthy within its
  own bound plus three probes, where it used to stay "running".
- A deploy's stop costs at most the job in flight; a kill costs one redelivery.
- A scheduler restarted across a cron time applies the schedule's declared policy, once.
- **Breaking:** a `ScheduleDefinition` without `misfire=` raises `TypeError` at import; a shared
  store with no `ping()` refuses a boot that requires it; an app on the outbox meets one new
  revision; `DrainResult` gains a field; the reference app's worker and scheduler, and every
  generated profile with one, gain a healthcheck their dependants wait on.

## Open

- **A Redis client without a socket timeout** holds every request the rate limiter counts when
  Redis stops answering, readiness included, because the stores keep redis-py's defaults.
  Readiness's own probe is bounded; the client is bounded by the URL
  (`?socket_timeout=2&socket_connect_timeout=2`), which `terp guide deployment` says. Changing
  the adapter's default is a decision about every store call, not about readiness.
- **The database check** is bounded by the driver and the pool, not by the 2-second probe bound:
  a database that accepts connections and never answers holds it until the driver gives up
  (`connect_timeout` in `DATABASE_URL`). psycopg's own default is 130 s, and on a Windows host
  it waits all of it even for a refused connection, so a database that is simply gone holds the
  check that long there (measured, *How it was built*); in a Linux container the refusal
  answers at once.
- **Two schedulers** still hold no lock between them. On the outbox and the database ledger the
  second loses the compare-and-set and enqueues nothing; on a broker queue both publish.
- **A job that kills its worker every time** is redelivered every time under late
  acknowledgement; the retry budget counts a handler's failures, not redeliveries.
- **A read-only root filesystem** needs a writable `TMPDIR` (a tmpfs) for the heartbeat, which the
  generated profile does not render.

## How it was built

Measured on the development machine (Windows, where a refused local connection takes about two
seconds):

- **A mandatory store going away** (`test_readiness.py`): terp-cap-redis' three stores over
  redis-py's own client and real sockets to an in-test server speaking the Redis protocol, all
  three required. Stopped: readiness 503 after 4.1 s (the rate limiter's refused connection, then
  the probe). Started again on the same port: 200 after 0.03 to 0.4 s. Silenced (accepting and
  never answering): 503 after 2.0 s, a second probe answered at once, 200 within 0.3 s of the
  server answering again. All under the 30-second bound.
- **The database going away** (`test_readiness_postgres.py`): the app reaches PostgreSQL through
  a relay the test cuts and restores, held to the same 30-second bounds in CI's PostgreSQL lane.
  Its first run against a real server (PostgreSQL 17) found the test wrong on both platforms. On
  Linux the relay never stopped accepting, because a listener closed while another thread is
  blocked in `accept` goes on listening, so readiness stayed 200 and the test failed. On Windows
  the first probe blocked for 130 s and then answered 503, and the test passed, because the
  bound was checked between polls and not on the answer. The relay now shuts its listener down
  before closing it, and each answer is held to the bound. Measured then, on Linux
  (`python:3.14-slim` beside `postgres:17`, the lane's three modules, 80 passed in 84 s): 503
  0.02 s after the cut and 200 0.01 s after the restore, in three runs. On Windows psycopg waits
  out its connect timeout for a refused connection, so the test gives it `connect_timeout=5`
  there, as a deployment bounds its driver: 503 after 5.0 s, 200 after 0.03 s.
- **The heartbeat checks on a Docker engine** (Docker Desktop, Engine 29.1.3, Compose 2.40.3).
  The reference app's production profile, rendered and built for real with `TERP_RELEASE_TAG`
  set, came up under `docker compose up -d --wait` in 34 s with exit 0, the worker and the
  scheduler healthy on their heartbeats (the probe's line: `{"heartbeat": "worker",
  "age_seconds": 3.9, "stale_after_seconds": 60.0}`). The worker's loop stopped with `SIGSTOP`
  (`kill -STOP` on its process inside the running container; `init`'s process stays up) turned
  the container unhealthy 79 s later, after three failed probes at heartbeat ages 61.5, 71.8 and
  82.3 s: within its 60-second bound plus three probes. `SIGCONT` turned it healthy at the next
  probe, 10 s later, with no restart. The scheduler, stopped the same way: unhealthy after 80 s,
  healthy 10 s after `SIGCONT`. A `docker compose stop` of each ended it on SIGTERM within 2 s,
  exit code 0.
- **Redelivery after a kill** (`test_worker_lifecycle.py`): two worker processes over one
  database. The first, `terp jobs worker --forever --lease-seconds 2`, takes the job and is
  killed in it; the row stays pending, leased to the dead claim, attempts 0. The second, started
  after the lease lapsed, runs the same row to the end: two runs, in two process ids, one
  `dispatched` row (10.5 s, most of it two processes importing the platform). A stop mid-batch
  finishes one job and releases the other two, which another worker claims at the same moment;
  the real SIGTERM path runs on POSIX.
- **Misfire after a restart** (`test_scheduler_adapters.py`): each adapter, two instances sharing
  only a database file. Fired at 09:00, restarted at 11:30: the run-once schedule runs once, late,
  for 11:00 (ten and eleven folded), the skip schedule records 11:00 skipped, a second restart
  owes nothing, and noon runs on time for both. A first start records a baseline and runs nothing.
- **Heartbeat staleness** (`test_worker_heartbeat.py`): the generated probe run as Docker runs it,
  in a process of its own, passes a fresh heartbeat and fails one past its bound, a missing one, a
  broken one and another role's. A worker loop stuck in a job writes nothing more while an idle
  one beats every poll.
- **Mutation checks**: 28 mutants, each a guard removed or weakened in turn with the tests that
  hold it run against it, among them readiness dropping the stores, an unbounded probe, a
  hanging probe asked again, the rate limiter refusing `/health`, a skip run late, a late slot
  called on time, both ledgers overwriting, a lost compare-and-set committing its row, a stopped
  worker that keeps claiming or releases nothing, an expired lease never reclaimed, Celery
  acknowledging on receipt, a heartbeat that outlives its process and a probe that never calls
  one stale. All 28 fail the suite (one by hanging it: a worker that ignores its stop claims and
  releases the same rows forever). A twenty-ninth, the forever loop's own beat after each drain,
  survived because the drain already beats before each claim, so that beat was removed.
