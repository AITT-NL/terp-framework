# terp-cap-realtime

The opt-in, sanctioned realtime surface for Terp apps: typed SSE and WebSocket
channels behind one generated-client handshake.

## Backend

Declare and register a channel once:

```python
from pydantic import BaseModel
from terp.capabilities.realtime import RealtimeChannel, register_channel

class Notice(BaseModel):
    sequence: int
    text: str

NOTICES = register_channel(RealtimeChannel("system.notices", Notice))
```

The default audience is the authenticated principal. Publish to that explicit
audience (a tenant resolver can return a tenant id instead; use
`global_audience` only for intentionally global broadcasts):

```python
await publish(NOTICES, Notice(sequence=1, text="Ready"), audience=str(user_id))
```

A bidirectional WebSocket channel adds an inbound Pydantic model + handler. Its
subscription requirement defaults to VIEWER; its inbound requirement defaults
to EDITOR, and both can be typed `Role`/`Permission` objects. The handler receives
the authenticated principal and a validated model, never an untyped frame. Each
frame runs in a fresh session that closes when its sync or async handler returns;
apps with a custom session seam pass it as `message_session_provider` to
`configure_realtime`.

The self-registering `ModuleSpec` mounts:

- `POST /api/v1/realtime/tickets` — authenticated by the app's normal principal
  provider; applies channel authority; returns a 30-second opaque ticket.
- `GET /api/v1/realtime/sse/{channel}` — redeems an SSE ticket once.
- `WS /api/v1/realtime/ws/{channel}` — redeems a WebSocket ticket once.

The bearer token stays server-side; it never appears in the URL. Configure
`principal_validator` to recheck expiry/revocation during long-lived connections.
Single-process apps use bounded in-memory broker/ticket stores. Multi-replica
apps wire a shared broker and `RedisConnectionTicketStore` (atomic GET+DEL),
shipped behind the `terp-cap-redis[realtime]` extra
(`terp.capabilities.redis.realtime`).

## Serving an app that has channels

**Mounting this capability changes how the app must be served.** A channel's
stream is a task with no end condition of its own: it closes when the client
goes away, and until then it keeps the connection open on purpose. uvicorn's
`timeout_graceful_shutdown` is unset by default, and unset means *wait for
in-flight tasks* — so with one browser tab subscribed, a shutdown never
completes. In the dev loop that is a reloader that never restarts; in
production it is a container that stops only when the orchestrator kills it.

So bound it, explicitly, in every invocation:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 8
```

The template and the example app ship this bound already (ADR 0108): **3**
seconds wherever `--reload` is on, because the reload loop pays the wait on
every backend edit, and **8** seconds in both images, which sits under Compose's
ten-second default `stop_grace_period` so the process exits on its own terms
rather than being killed mid-write. `terp dev` carries the same 3-second bound
and takes `--shutdown-timeout` to change it.

Pick your own number by the same two questions: how long a genuine in-flight
request may need, and how long the thing that stops your container waits before
it stops asking. The value has to be under the second one, or the bound never
takes effect.

## Frontend

App modules use the package-root hook, never raw transports:

```tsx
const notices = useRealtimeChannel({
  channel: "system.notices",
  validate: isNotice,
});
```

The hook mints its ticket through the generated authenticated client, opens the
native transport internally, and validates every JSON payload with the supplied
type guard before exposing it. A transient disconnect closes the consumed-ticket
transport and remints with bounded exponential backoff; `close()` cancels both a
pending mint and scheduled reconnects.
