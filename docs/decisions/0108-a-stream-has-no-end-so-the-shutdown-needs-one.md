# 0108 — A stream has no end, so the shutdown needs one

- **Status:** Accepted
- **Date:** 2026-09-01
- **Relates:** [ADR 0008](0008-event-bus-catalog-and-typed-emit.md) (the event bus the realtime
  subsystem was designed to be driven by — its "remains future work" sentence is corrected here),
  [ADR 0062](0062-production-deployment-profile.md) (the production profile, whose image CMD this
  changes), [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (one pattern,
  escapable by explicit declaration — the shape the bound takes),
  [ADR 0107](0107-the-dev-server-names-who-may-frame-it.md) (the previous decision about a value
  that is deliberately different in development and in production).

---

## Context

This record does two things, because the second is why the first went unnoticed for so long.

### The capability shipped without a record

`terp-cap-realtime` provides typed SSE and WebSocket channels behind one generated-client
handshake. It is mounted by the example application, exported from `@terpjs/react-core`'s public
surface as `useRealtimeChannel`, and present in every tagged release.

**No decision record describes it.** Two mention the word: ADR 0002 lists `realtime` among the
module declarations, and ADR 0008 says the realtime subsystem "is designed to be driven by this
bus … it remains future work" — a sentence that has been false for several releases while the
component sat in the tree next to it. It has never appeared in the CHANGELOG either: the word
does not occur in that file, once, in any release.

This is an outlier rather than a pattern — the environment-seam work of the same period is
changelogged twice over — but it is the kind of outlier that compounds. A capability nobody wrote
down is a capability whose consequences nobody reasoned about in the open, and the defect below is
exactly one of those consequences. So this ADR is also the record the component never had.

### A stream is a task with no end condition

A channel's stream is a loop with a fifteen-second keepalive. It terminates when the client goes
away and not otherwise; staying open is the feature.

uvicorn's `timeout_graceful_shutdown` defaults to `None`, and `None` means **wait for in-flight
tasks to finish**. Put those two facts together and a shutdown never completes while one browser
tab is subscribed. Nothing in the platform connected them:

- The flag appeared in **no file** in the repository — not the template, not the example, not the
  CLI, not a line of documentation.
- **All seven** invocations that start a server were bare: the example's compose file, dev image
  and production image; the template's three counterparts; and `terp dev` itself.
- The example application registers **two** channels, so the reference implementation shipped the
  defect it demonstrates.
- The capability's README had two sections, Backend and Frontend. Nothing on serving.

The cost is ordinary and constant rather than dramatic, which is why it survived. With one tab
open, the first backend edit hangs the reloader until someone restarts the container by hand — a
symptom that reads as "the reloader is flaky", not as "the shutdown is unbounded". In production
a restart blocks until the orchestrator gives up and sends `SIGKILL`, so the process is killed
mid-write instead of closing its work.

`terp dev` is the sharpest instance and the last one anybody would look at, because it is the
platform's own command: the compose files and images belong to the app and can be edited, and
that argv cannot be.

## Decision

**Every invocation that starts an ASGI server carries an explicit
`--timeout-graceful-shutdown`.** Two values, by what the wait costs where it is paid:

| Where | Seconds | Why |
|---|---|---|
| `--reload` loops — both compose files, `terp dev` | **3** | The reload loop pays this on every backend edit. A development request needing more than three seconds is not worth holding the restart for. |
| Served processes — both dev images, both production images | **8** | Under Compose's ten-second default `stop_grace_period`, so the process exits on its own terms rather than being killed. |

Three properties make this a decision rather than a default.

**The bound is per-invocation, and that is not an oversight.** uvicorn is started by the app's own
compose file, its own image, or `terp dev`; none of those routes through `create_app`, so there is
no seam at which the framework could apply this centrally. The argv *is* the declaration — visible
and greppable in the app's own files, which is ADR 0103's shape.

**`terp dev` gets the escape, because it is the one an app cannot edit.**
`dev_plan(shutdown_timeout=…)`, surfaced as `terp dev --shutdown-timeout`. A non-positive value is
refused rather than passed through: uvicorn reads `0` as "cancel in-flight work immediately",
which is a different decision from the one this argument names, and taking it silently would let
an app think it had set a bound when it had disabled one.

**The control is a test, since no runtime check can see an argv.**
`tests/architecture/test_serving_shutdown.py` pins each site and each value, and its last test
greps every candidate file for an argv that starts a server without the flag — so a *new* way to
serve fails even though the test never named it. That is the half that matters: the defect was
never that the value was wrong, it was that nothing noticed there was no value.

## Consequences

- An in-flight request still running at the bound is cancelled rather than awaited. That is the
  intended trade and it is worth stating plainly: an application whose ordinary requests take
  longer than eight seconds should raise its own number, and should probably be using the durable
  queue instead.
- The numbers are the platform's, not every app's. Both are in files the app owns, and the README
  gives the two questions to re-derive them: how long a genuine request may need, and how long the
  thing that stops the container waits before it stops asking. A bound above the second number
  never takes effect.
- ADR 0008's "remains future work" sentence is corrected in the same change, so the two records no
  longer contradict each other about whether the subsystem exists.
- This does not give the realtime capability a full design record — what it does, why tickets
  rather than bearer tokens in URLs, why a shared broker for multiple replicas. The README carries
  that. What was missing and is now supplied is a decision record that acknowledges the component
  ships and reasons about one consequence of running it.
