# 0222 — A refused start names every refusal at once

- **Status:** Proposed on 2026-11-24. Held by `tests/architecture/test_boot_refusals.py`
  (several refusals together, one refusal unchanged, the production refusals together, where
  the checks stop, nothing configured while refused, and the routes read as served) and by
  every existing test of a single refusal, whose words are unchanged.
- **Date:** 2026-11-24.
- **Relates:** changes how [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md),
  [ADR 0208](0208-a-route-holds-every-timestamp-it-reads-to-its-offset.md) and every
  other check in `create_app`'s declaration phase report what they find, not what they refuse.
  [ADR 0212](0212-an-app-compares-the-routes-it-serves-with-its-record-before-it-serves.md)'s
  comparison and [ADR 0218](0218-a-process-that-cannot-write-its-storage-root-does-not-start.md)'s
  boot checks keep their place, after mounting, and run only when nothing else refused.

## Context

`create_app` asks a series of questions about an app's declarations before it configures
anything: every route of a public module declares its own policy (ADR 0148), every module's
routes are guarded, every operation and permission it names is declared, the stores a
deployment requires are the shared kind, a production boot's security, password, audit and
attribution settings hold, and more. Each check raised a `BootError` at its first finding, and
the request timestamps (ADR 0208) were judged only once every router was mounted, after
everything else had passed.

So an app behind on several requirements learned of one per start. Friction reported from
upgrading an app across many releases: a schedule's missed-tick setting, then a public
route's policy, then timestamps needing a UTC offset, each visible only once the one before it
was fixed. The questions are independent; only the order in which the code asked them made
them arrive one by one.

## Decision

1. **The declaration checks are asked together and answered together.** Each runs; its refusal
   is kept, and the next runs. When they are done, the refusals are raised as one `BootError`:
   - one refusal is the check's own error, re-raised as it was: its words, its type and its
     cause are unchanged, so every reader of a refused start (a deploy tool reading the log,
     a test matching the sentence) reads what it read before;
   - several are one error that says how many there are and numbers each, its own lines
     indented under its number.
   Either way the error carries each refusal's message on `refusals`, in the order found.
2. **The request timestamps are judged with them.** `module_timestamps_refusal` reads each
   module's own router, nested routers included, and names every route as it will be served,
   under `/api/v1/<name>`; nothing is mounted or included to do it, and the finding is the
   sentence the check after mounting would give. That check still runs after mounting, over
   every route, the framework's own included.
3. **A check that cannot run says so, and the answer stops there.** A refusal raised directly
   (the control plane's settings unusable, a store readiness cannot ask) is kept and ends the
   checks. An error that is no refusal, raised after one was kept, is most likely its
   consequence (a validator reading a declaration an earlier check refused): the refusals are
   raised, chained to it, with a line naming where the checks stopped. Raised before any
   refusal, it propagates untouched.
4. **Nothing is configured while anything is refused.** The checks end before the first
   `configure_*` call that follows them (audit, events, jobs, schedules and the rest), as the
   first refusal did before, so a refused composition leaves no more process-wide state behind
   than it did. Logging, set up before any check so a refusal can be logged, is the one step
   before them, as it always was.
5. **The later checks keep their place and their meaning.** The migration guard, the checks
   after mounting (timestamps over every route, tuple schemas), the comparison with
   `authz-surface.json` (ADR 0212) and the image's boot checks (ADR 0218) run only once the
   declarations passed. The comparison in particular is never combined with another refusal:
   a deploy tool tells it apart from the rest, and an app refused for something else is not
   the app the record describes.

## Consequences

- **An app upgraded across many releases meets its declaration refusals in one start.** The
  two the report met in sequence after the first, a public route's policy and a timestamp
  without its offset, now arrive together.
- **A deploy tool reading a refused start's log gets every refusal.** Studio reads the
  sentence after `BootError:` (up to 4000 characters) and recognises the access-record
  refusal by its own words, which this never combines with another; the runner's planned
  boot-preflight reports the app's own message, which now lists all of them.
- **Each module route's parameters are read twice at boot**, before and after mounting: a walk
  of each route's dependencies, once per process.
- **`create_app`'s module made room.** The cycle finder of `validate_requires` moves,
  unchanged, into `terp.core._requires_graph`, so `app.py` shrinks (2281 to 2262 lines in
  `OVERSIZED.json`).

## Not done

- **A requirement that fails before `create_app` is not among them.** A schedule declared
  without its missed-tick setting is a `TypeError` where the control plane is imported
  (`ScheduleDefinition.misfire` is a required keyword, ADR 0191), so the app never reaches
  the checks this collects. A build-time rule that reads every `ScheduleDefinition` for it
  would let `terp check` list it with every other finding; it is not part of this decision.
- **The checks after mounting are still asked after the declarations passed**, and the tuple
  schemas only once the app is built: they need the finished app.

## Alternatives considered

- **Keep raising at the first refusal, and add a `terp verify` check that collects them.** A
  second code path asking the same questions drifts from the first, and the start itself
  would still answer one at a time, which is where a deploy tool reads it.
- **Collect through the whole of `create_app`, mounting included.** It would configure the
  process while refusing it, and the checks after mounting read an app whose declarations
  were refused.
- **Raise a new exception type for several refusals.** Every reader catches `BootError`; a
  refusal is still a refusal however many there are.
