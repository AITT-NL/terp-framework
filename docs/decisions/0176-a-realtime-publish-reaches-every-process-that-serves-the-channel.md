# 0176 — A realtime publish reaches every process that serves the channel

- **Status:** Accepted and implemented (2026-10-06). `RedisRealtimeBroker` ships in
  `terp-cap-redis[realtime]`; `configure_realtime(require_shared_broker=True)` refuses a
  per-process broker. Held by `tests/architecture/test_realtime.py` (the shared marker and the
  promise at each point it is checked) and `tests/architecture/test_redis_stores.py` (a publish
  on one broker reaching a subscriber on another, a dropped connection ending the stream).
- **Date:** 2026-10-06
- **Relates:** [ADR 0078](0078-redis-backed-shared-stores.md) (the Redis adapters this joins),
  [ADR 0036](0036-distributed-throttle-store.md) (the opt-in shared-store promise this mirrors),
  [ADR 0045](0045-durable-outbox.md) (the worker process),
  [ADR 0108](0108-a-stream-has-no-end-so-the-shutdown-needs-one.md) (how a stream ends)

---

## Context

The realtime broker's default is `InMemoryRealtimeBroker`: one bounded queue per subscriber, in
the process that holds the connection. A publish reaches the subscribers of the process that
published, and no others. The docstring and `terp guide realtime` said to replace it "when you
run more than one replica", and named the seam to do it with, `configure_broker`. No shared
implementation existed. The only Redis piece for realtime was the ticket store, so a deployment
that needed a shared broker had to write one.

"More than one replica" also undersold when it was needed. The guide's own advice is to publish
"from a service, an _after_write hook, or a job handler". A job handler on the durable queue runs
in `terp jobs worker`, a separate process that serves no transport. Its publish went into a
broker nobody subscribes to, and nothing said so. That is an app with one web replica and one
worker, which is the deployment the worker container exists for (ADR 0045).

Nothing would have caught it either. Core's per-process defaults for idempotency, throttling
and cache each have an opt-in promise, `require_shared_*_store`, that boot checks. The broker
lives in a capability, where core's boot cannot see it, and it had no promise of its own.

## Decision

**Ship the shared broker.** `RedisRealtimeBroker` joins `RedisConnectionTicketStore` behind
`terp-cap-redis[realtime]`. A publish goes to Redis pub/sub, and every process holding a
subscriber on that topic receives it.

- **Each subscriber holds its own pub/sub connection** for as long as its transport is open.
  That bounds a slow consumer the way the in-process queue does. Redis buffers for one
  subscriber up to the server's `client-output-buffer-limit pubsub`, then drops the connection.
  One connection per subscriber costs a connection per open stream. A per-process relay would
  share one, at the price of a background task bound to one event loop. The simpler shape is
  right until a deployment's connection count says otherwise.
- **`publish` runs the synchronous client on a worker thread**, so it works from any event
  loop without blocking it, including one `asyncio.run` opened for a sync hook (which the
  in-process broker already supports). `stream` opens an asyncio client inside the subscriber's
  own loop.
- **Delivery stays fire-and-forget.** A message published while nobody listens is gone, in
  process and through Redis alike. A channel whose client must not miss a message re-reads its
  state on reconnect. This change is about reach, not durability.
- **The one governed redis import serves both clients.** The capability's escape-hatch budget
  stays at one marker.

**A subscription the broker ends is one thing to a transport.** `BackpressureError` becomes a
kind of the new `SubscriptionEnded`, and the transports close on `SubscriptionEnded`. A shared
broker whose backend dropped the connection ends a stream the same clean way a slow consumer
does, and the browser's reconnect takes it from there.

**Shared is a mark, and a deployment can promise it.**

- `mark_shared_broker` / `is_shared_broker` follow core's `mark_shared_*` markers. The Redis
  broker marks itself; an app's own adapter (managed messaging) marks itself the same way.
- `configure_realtime(require_shared_broker=True)` refuses a per-process broker at each point
  one could slip in:
  - at once, if one is already installed when the promise is made;
  - at once, if one is installed after the promise;
  - at first use, if nothing was installed and the lazy default would be created.

  Every publish and every transport reaches the broker through `get_broker()`, so the last case
  fails the first publish or subscription instead of dropping messages in silence.

**The guide says when.** The per-process default breaks with a second replica, and with one
replica once a job handler runs in `terp jobs worker`. The realtime topic says both, and shows
the wiring: both Redis adapters, and the promise.

## Consequences

**Nothing changes for a deployment that sets nothing.** The default stays in process, and the
promise is opt-in, like core's.

**A transport that caught `BackpressureError` itself still works,** because the existing error
is now a subclass of `SubscriptionEnded`. Code that wants every reason a subscription ended
catches the base.

**Verified against a real server as well as the fake.** Two OS processes on one Redis 7: the
publish from the second reached the subscriber in the first. Killing the subscriber's
connection server-side ended the stream as `SubscriptionEnded`, caused by redis-py's
`ConnectionError`, and left no channel subscribed. The suite runs over an in-repo pub/sub double,
as the other Redis adapters' suite does. The live run is not part of the gate.

**Not decided here.** Whether the template should wire Redis for an app that selects realtime
and runs a worker. It wires no Redis today for any store. That belongs with a production profile
for the template as a whole, not with one capability.
