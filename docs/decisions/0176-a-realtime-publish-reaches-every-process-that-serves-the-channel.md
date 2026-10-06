# 0176 — A realtime publish reaches every process that serves the channel

- **Status:** Accepted and implemented (2026-10-06). `RedisRealtimeBroker` ships in
  `terp-cap-redis[realtime]`; `configure_realtime(require_shared_broker=True)` refuses a
  per-process broker. Held by `tests/architecture/test_realtime.py` (the shared marker, the
  promise at each point it is checked, and a subscription that cannot start answered as a
  `503` / a close `1013` rather than a `200` / an accept) and
  `tests/architecture/test_redis_stores.py` (a publish on one broker reaching a subscriber on
  another, the database index in the channel names, a publish Redis does not take dropped
  without failing, a dropped, silent or reconnected connection ending the stream, and both
  halves of a subscriber's connection closed however it ends).
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
- **Pub/sub is server-wide.** A channel belongs to the Redis server, not to one of its numbered
  databases, so two deployments on one server with the default namespace would hear each
  other even on different databases. The channel names carry the publishing client's database
  index (`<namespace>:<db>:realtime:<topic>`). Deployments that share a server *and* a
  database must use distinct namespaces; nothing can tell them apart otherwise.
- **`publish` runs the synchronous client on a worker thread**, so it works from any event
  loop without blocking it, including one `asyncio.run` opened for a sync hook (which the
  in-process broker already supports). Each subscriber opens an asyncio client inside its own
  loop. `from_url` builds both with connecting and each reply bounded at two seconds, and
  without retries; the shared stores' client keeps redis-py's defaults.
- **Delivery stays fire-and-forget,** and that includes a publish Redis does not take. A
  message published while nobody listens is gone, in process and through Redis alike. A
  publish that meets a connection error or a timeout is dropped with a warning in the log
  (the channel prefix, never the payload), because a publish rides a write path: one raised
  from an `_after_write` hook would roll back the write it reports, and an unbounded wait
  would hold the request. A channel whose client must not miss a message re-reads its state
  on reconnect. This change is about reach, not durability.
- **A quiet subscription is checked, not trusted.** A connection that dies without a reset
  reaching the client (a dropped route, a frozen server) leaves a blocking read waiting
  forever on a channel nobody publishes to. The subscriber reads with a timeout instead
  (`get_message`, 30 seconds by default); idle that long, it pings Redis, and if nothing at
  all arrives within as long again, the subscription ends. A ping whose write fails ends it
  at once.
- **A reconnect ends the stream too.** redis-py may reconnect a dropped pub/sub connection
  and subscribe again on its own; the messages of the gap are gone without a trace. The
  subscriber treats a second SUBSCRIBE confirmation as the end of its subscription, so the
  browser reconnects and re-reads.
- **Both halves of a subscriber's connection close however it ends,** and a close that fails
  neither skips the other nor replaces the error that ended the subscription.
- **The one governed redis import serves every client.** The capability's escape-hatch budget
  stays at one marker. The floor is `redis>=5.0.1`, the first release with the asyncio
  `aclose()` the subscriber closes with.

**A transport subscribes before it answers.** An SSE `200` and a WebSocket `accept` both tell
the browser it is subscribed, and the browser's hook resets its reconnect backoff on either.
A subscription that failed after the answer looked to the browser like a stream that opened
and dropped, so it reconnected every second, indefinitely. `RealtimeBroker.subscribe(channel)`
starts a subscription and returns its messages once it is live; its default returns
`stream(channel)`, so an adapter that cannot fail to start needs nothing new. The Redis broker
overrides it to connect and have the SUBSCRIBE confirmed first, and raises
`SubscriptionEnded` when it cannot. The transports call it before they answer: SSE then
answers `503` (`RealtimeUnavailableError`, code `realtime_unavailable`), and a WebSocket is
closed `1013` (try again later) before it is accepted, so the browser backs off. Anything else
raised there, such as `SharedBrokerRequiredError`, is a wiring fault and surfaces as one (a
`500` the server logs), never as a `200` that ends at once. The ticket is spent either way:
it is single-use, and it was redeemed first.

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
  fails the first publish or subscription instead of dropping messages in silence. The refused
  default is not installed, so a `configure_broker` that comes later, or the promise made
  again, still works.
- The promise stays until it is withdrawn. A later `configure_realtime` call that leaves
  `require_shared_broker` out (its default is `None`) keeps it; `require_shared_broker=False`
  or `reset_realtime_configuration()` withdraws it.

**The guide says when.** The per-process default breaks with a second replica, and with one
replica once a job handler runs in `terp jobs worker`. The realtime topic says both, and shows
the wiring: both Redis adapters, and the promise.

## Consequences

**Nothing changes for a deployment that sets nothing.** The default stays in process, and the
promise is opt-in, like core's.

**A transport that caught `BackpressureError` itself still works,** because the existing error
is now a subclass of `SubscriptionEnded`. Code that wants every reason a subscription ended
catches the base.

**A custom broker adapter keeps working,** since `subscribe` has a default. One whose
subscription can fail to start overrides it to raise `SubscriptionEnded`, so its transports
refuse rather than answer.

**Verified against a real server as well as the fake,** on Redis 7 with redis-py 8.1; the
checks up to the unreachable publish ran again on 5.0.1, the floor. Two OS processes: the
publish from the second reached the subscriber in the first. A publish on database 1 did not reach a subscriber on database 0 under the same
namespace; one on database 0 did. Killing the idle subscriber's connection server-side ended
the stream at once as `SubscriptionEnded`, caused by redis-py's `ConnectionError`, and left no
channel subscribed. Freezing the server (`docker pause`) under an idle subscriber with a
two-second interval ended the stream four seconds into its wait, on the unanswered ping. A
publish to a port nobody listens on returned at once, and to an unroutable address after two
seconds, each with one warning; `subscribe` against either was refused after the same time.
Through the transports: with Redis unreachable, SSE answered `503` and the WebSocket was closed
`1013` before accept; with it up, a publish made straight after the SSE route returned reached
the stream. The suite runs over an in-repo pub/sub double, as the other Redis adapters' suite
does. The live run is not part of the gate.

**Not decided here.** Whether the template should wire Redis for an app that selects realtime
and runs a worker. It wires no Redis today for any store. That belongs with a production profile
for the template as a whole, not with one capability.
