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
apps wire a shared broker and `RedisConnectionTicketStore` (atomic GET+DEL).

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
