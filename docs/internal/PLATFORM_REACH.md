# Terp — Platform Reach: the designed answers to what Terp does not yet supply

> **Purpose.** Terp refuses almost no application shape and *supplies* one. This
> document turns that gap into a program: for every scenario the platform permits
> but does not serve, a designed solution — the seam, its enforcement, its failure
> modes, its tests, and what it deliberately does not do.
>
> **Status:** proposal for acceptance. Nothing here is built. Each item carries its
> own status line; where an item is a refusal, the refusal is the deliverable.
> **Audience:** platform/core team + agents.
>
> **Relationship to existing docs (no drift):**
> - [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md) remains the
>   architectural source of truth. This document adds nothing to it that is not
>   also proposed as an ADR.
> - [ADR 0114](../decisions/0114-terp-supplies-the-inside-of-a-deployable.md) states
>   the position this program acts on: one deployable is supplied, a second is
>   permitted and unsupplied. **Part I is ADR 0114 decision 4, designed.**
> - [ADR 0111](../decisions/0111-flexibility-is-bounded-by-legibility-not-by-capability.md)
>   fixes the method — a socket vocabulary rather than a catalogue of
>   implementations — and every item here is written to it.
> - [ADR 0006](../decisions/0006-cross-cutting-controls-and-opinionation-policy.md)
>   fixes the bar — the quadruple — and no item ships without all four parts.
> - [docs/internal/STATUS.md](STATUS.md) tracks what is built. When an item here
>   lands, it moves there and its section becomes an ADR.

---

## 0. How to read this

Fourteen items and eight refusals. Each item has the same shape, so a reader can
skip to the part they are deciding:

| Sub-heading | What it answers |
|---|---|
| **Problem** | The evidence in the tree, not an opinion about it |
| **Design** | The seam, in Terp's own idiom, concrete enough to disagree with |
| **Enforcement** | The ADR 0006 quadruple, and the spec catalog entry it ships |
| **Failure modes** | What goes wrong in production, and what the design does about it |
| **Compatibility** | What an existing app must change (the answer is always *nothing*) |
| **Tests** | What would prove it, at build time, at runtime, and in CI |
| **Out of scope** | The refusals *inside* the item, so they are not re-proposed |

Every item also carries three classifications, because the platform already
requires them and a proposal that cannot state them is not ready:

- **Tier** — ADR 0006: **A** mandatory, **B** defaulted-overridable, **C** optional sugar.
- **Runtime applicability** — ADR 0084: `required`, `not-applicable`, or `deferred`,
  with the rationale that goes in the catalog entry.
- **Kind** — ADR 0111 decision 1: a **security invariant** (conformance), a
  **legibility contract** (truth-about-self), or the **application's own business**
  (no rule at all).

---

## 1. The method, and the bar

Three tests govern what may enter this program. They are not new; they are the
platform's own, applied to a class of proposals it has not faced before.

### 1.1 The quadruple (ADR 0006)

A concern may become a framework control only as all four of: a typed
control-plane registry with a safe default; a fail-closed runtime control; a
build-time test; and a budgeted escape hatch. **An item in this document that
cannot ship all four is a product decision, not a framework control, and belongs
in an application.** Two candidates were dropped from an earlier draft on exactly
this ground and are recorded in §17 rather than deleted.

### 1.2 The socket, not the catalogue (ADR 0111 decision 4)

For each thing a client might need that Terp has not shipped, the framework's job
is to define **what such a thing must declare about itself** and not to define its
implementation. The measure of success for this program is therefore *not* how many
capabilities ship. It is how many application kinds become buildable **per
capability** — because the vocabulary grows rarely and compatibly, while a
catalogue grows one release at a time and gates every client who needs something
new.

Concretely, that is why §6 (aggregation) and §7 (charts) are one design in two
halves and not two shopping-list entries, and why §9 (AI) is mostly *not* a new
subsystem.

### 1.3 The consumer test, amended (ADR 0099, and §14 below)

ADR 0099 declined thirteen components on the rule: *a component that cannot name a
consumer in this framework is declined.* That test is correct for keeping a
framework honest and is structurally unable to see an application's need — an
app's consumer is never in the framework. Left unamended it guarantees the
component surface can only ever grow toward what the framework already does.

§14 proposes the amendment: **or two independent applications asked for it**, with
the asking recorded so it is countable. Every UI item in this program is written
as though the amendment has passed; if it does not pass, §7, §10 and §12 fail with
it, and that is the honest consequence to weigh.

---

## 2. The program at a glance

| # | Item | Closes | Kind | Tier | Size | Wave |
|---|---|---|---|---|---|---|
| [R1](#3-r1--terp-cap-http-the-declared-egress-capability) | Declared egress capability | No sanctioned way to call anything | security invariant | A | L | 1 |
| [R2](#4-r2--the-event-relay-emit-that-crosses-a-process) | Event relay over a broker | `emit` cannot leave the process | app's business + invariant | B | L | 3 |
| [R3](#5-r3--trace-context-end-to-end) | Trace context end to end | Correlation dies at every HTTP hop | legibility | B | M | 2 |
| [R4](#6-r4--the-deploy-unit-declaration) | Deploy-unit declaration | A fleet is illegible to tools | legibility | B | M | 3 |
| [R5](#7-r5--audience-scoped-service-tokens-and-on-behalf-of) | Audience-scoped tokens + on-behalf-of | Audit stops at the process edge | security invariant | A | M | 3 |
| [R6](#8-r6--the-aggregation-seam) | Aggregation seam | Reporting is a hand-written query | security invariant | A | M | 1 |
| [R7](#9-r7--the-chart-primitive-and-the-data-palette) | Chart primitive + data tokens | Nothing can draw a number | app's business | C | M | 1 |
| [R8](#10-r8--the-search-seam) | Full-text search seam | Search is `ILIKE` or nothing | app's business | B | M | 2 |
| [R9](#11-r9--model-calls-streaming-and-long-running-work) | Model calls, streaming, budgets | An app cannot use a model | app's business | B | M | 2 |
| [R10](#12-r10--screens-that-are-not-a-record-the-instrument-archetype-and-the-component-zone) | Instrument archetype + component zone | A screen that is not a list | legibility | B | M | 2 |
| [R11](#13-r11--data-terp-does-not-own) | External/read-only models | Existing schemas are out of the zone | app's business | B | L | 3 |
| [R12](#14-r12--public-and-consumer-facing-surfaces) | Public shell + public routes | The shell assumes a session | security invariant | A | M | 2 |
| [R13](#15-r13--the-governed-zone-map) | The governed-zone map | Nobody can tell which rules apply where | legibility | B | S | 1 |
| [R14](#16-r14--governance-how-a-gap-becomes-a-decision) | The amended consumer test | The catalog cannot see an app's need | governance | — | S | 1 |

**Waves** are dependency order, not a schedule. Wave 1 items depend on nothing;
wave 2 items depend on wave 1; wave 3 items are independently large. Sizes are
relative (S ≈ days, M ≈ one release, L ≈ two releases with a spec release between)
and deliberately not calendar estimates — team capacity is not this document's to
assume.

---

# Part I — The between (ADR 0114 decision 4, designed)

---

## 3. R1 — `terp-cap-http`, the declared egress capability

**Status:** unbuilt · **Tier A** · **Kind:** security invariant ·
**Runtime applicability:** `required` (new rules), and it changes
`backend/no_raw_outbound_http` from a prohibition into a redirection.

### Problem

`no_raw_outbound_http` refuses `httpx`, `requests`, `urllib`, `urllib3`, `aiohttp`,
`socket` and `http.client` inside `app/modules/*`. The sanctioned egress
capabilities are webhooks (outbound *push*, SSRF-guarded, signed, retried), OIDC,
and a `SyncSource` the application writes — which, placed in a module, trips the
same rule and must be lifted into `app/foundation/` or take a budgeted hatch.

There is no capability whose job is *call something*. So the platform's only advice
on the most ordinary act in a multi-service system is a prohibition with nowhere to
go, and the path of least resistance is an escape hatch. ADR 0088 settled how to
think about that: the sanctioned path has to be easier than the wrong one, or it
will not be taken.

The rule's own catalog rationale concedes the remainder: *"Network-level egress
policy is deployment configuration, not a per-module framework seam."* True, and
not a client.

### Design

**A call names a declared target, never a URL.** That single decision is what makes
egress reviewable, deployable and testable at once: the address moves to
configuration (where `environment.schema.json` and its `resolvedBy` annotation
already live), the policy attaches to a name, and a reviewer reading a module sees
*which system* is being called rather than a string.

```python
# composition root — the one place a URL appears
from terp.capabilities.http import HttpEgress, Target, RetryPolicy

create_app(
    ...,
    egress=HttpEgress(
        targets=(
            Target(
                name="ledger",
                base_url=settings.app("LEDGER_BASE_URL"),   # declared env var
                timeout=Timeout(connect=2.0, read=10.0),     # required, no default
                retry=RetryPolicy(attempts=3, backoff="exponential-jitter"),
                auth=SealedBearer("LEDGER_TOKEN"),           # sealed config (ADR 0055)
                allow_private_network=True,                  # explicit, audited
                breaker=Breaker(failure_ratio=0.5, window_s=60, open_s=30),
            ),
        ),
    ),
    require_shared_breaker_store=settings.is_production,
)
```

```python
# app/modules/billing/module.py
module = ModuleSpec(
    name="billing",
    egress=("ledger",),          # the declared edge, like `requires`
    ...,
)

# app/modules/billing/service.py
from terp.core import egress

def fetch_balance(session: Session, account: str) -> Balance:
    response = egress.get(
        session,
        target="ledger",
        path="/v1/accounts/{account}/balance",   # a template, never an f-string
        path_params={"account": account},
        idempotent=True,
    )
    return Balance.model_validate(response.json())
```

Eight decisions carry the design.

1. **`egress` is a chokepoint on `terp.core`, like `enqueue` and `emit`.** It takes
   the `session` for the same reason they do: the audit record of the call is
   written on the caller's session, so an egress that happened is on the same
   trail as the write that caused it.
2. **The target set is declared on the `ModuleSpec` and checked at boot.**
   `egress=("ledger",)` extends ADR 0087's vocabulary a second time — the manifest
   already lists what a module depends on; an outbound system is a dependency. A
   call to an undeclared target raises `EgressError` at runtime; an undeclared
   *target name* (one no composition root installed) fails the boot, before any
   router is mounted, naming the module.
3. **A path is a template with bound parameters, never a built string.** The
   companion rule refuses an f-string / `%` / `.format` / `+` in `path=`, for the
   reason `no_dynamic_sql` refuses it in `text()`: a built path is how a caller
   walks out of the base URL (`path="/v1/../../admin"`) or reflects user input into
   a URL. Path params are percent-encoded by the capability, and a param that
   introduces a `/` or a `..` segment is refused rather than encoded away silently.
4. **SSRF protection is the webhooks capability's, reused.** The existing
   `terp.capabilities.webhooks.ssrf` resolver guard moves into a shared internal
   module both capabilities import: resolve the host, refuse loopback / link-local
   / private / multicast / reserved ranges unless the target declares
   `allow_private_network=True`, and re-check after redirects (redirects are
   followed at most once, to the same host, and never cross-scheme).
5. **Timeouts are required, and there is no default.** A `Target` without a
   `Timeout` fails construction. This is the difference between a control and a
   convention: the most common production incident from hand-rolled egress is an
   unbounded read holding a worker forever, and a default value is a number
   somebody will inherit without choosing.
6. **A call inside an open write transaction is refused.** This is the sharpest
   control in the design and the one most likely to be argued with, so the reason
   goes in the error message: a network call made while a write transaction is open
   holds a database connection for the duration of a remote system's bad day, and
   couples the local commit to a remote effect — the dual-write hazard ADR 0050 was
   built to avoid, which is why `SyncSource.pull` runs in the job handler and not in
   an `_after_write` hook. The sanctioned shape is: write, commit, and let the job
   the outbox already scheduled make the call. The opt-in is
   `egress.get(..., allow_in_transaction="reason")` — a string, not a boolean, so
   the reason is in the diff and greppable.
7. **Retries are bounded, jittered, and only for idempotent calls.**
   `idempotent=True` is on the call, not the target, because it is a property of the
   operation. A non-idempotent call is attempted once unless the caller supplies an
   `idempotency_key`, which the capability sends as the `Idempotency-Key` header —
   the same contract Terp's own inbound idempotency (ADR 0077) implements, so two
   Terp services compose correctly by default.
8. **The breaker is shared or it is not a breaker.** Per-instance breaker state in
   a four-replica deployment means a failing dependency is hammered by three
   replicas that have not noticed. `BreakerStore` follows the exact shape of
   `ThrottleStore` / `IdempotencyStore` (ADR 0036/0078): an in-memory default,
   a Redis adapter in `terp-cap-redis`, a `mark_shared_breaker_store` marker, and
   `require_shared_breaker_store=True` failing the boot in production. A breaker
   store error fails **closed** (the call is refused), consistent with the throttle
   store's posture.

**What is audited.** Every call emits an audit record: target name, method, path
*template* (never the interpolated path), response status, duration, attempt count,
breaker state, and the request-id / trace-id. Never the body, never query values,
never headers. A path template plus a status is enough to debug and cannot leak a
customer identifier; the interpolated path cannot make that promise.

**Response handling.** `egress` returns a typed `EgressResponse` (status, headers
subset, `json()`, `text()`, `content` capped by a per-target `max_response_bytes`
with a streaming refusal above it). A non-2xx does not raise by default — a 404
from an upstream is often a normal state — but `raise_for_status=True` maps the
status onto a typed `AppError` so the module's own error envelope stays uniform.

### Enforcement (the quadruple)

| Layer | Control |
|---|---|
| Control plane | `EgressPolicy` in the control plane; a target with no timeout, no host, or an unsealed credential fails construction (safe default = nothing is reachable) |
| Runtime, fail-closed | Undeclared target → `EgressError`; undeclared module edge → `BootError`; SSRF-refused host → refused before connect; open write transaction → refused; breaker store error → refused |
| Build-time | Two new rules (below), plus `no_raw_outbound_http` retargeted with a remediation that names the capability |
| Escape hatch | `# arch-allow-egress-target-declared: <reason>`, budgeted; `allow_in_transaction="<reason>"` at the call site |

**New spec catalog entries** (`terp-spec`, both `static-portable`):

- `backend/egress_targets_are_declared` — a module calling `egress.*` with a target
  its `ModuleSpec` does not list is refused. `runtime.applicability: required` (the
  composition root sees every spec and every installed target, so the boot check is
  the earlier, better-located half).
- `backend/egress_paths_are_static` — `path=` must be a literal template.
  `runtime.applicability: not-applicable` (an interpolated string is
  indistinguishable from a literal one by the time it reaches the client).

Both need corpus violation/compliant samples, which flips their `corpus` flag and
drops them from `corpus/PENDING.json`.

### Failure modes

| Failure | What the design does |
|---|---|
| Upstream hangs | Required read timeout; worker released |
| Upstream flaps | Shared breaker opens; calls fail fast with a typed error |
| Upstream slow under retry | Jittered exponential backoff, attempt cap, and the attempt count is audited so the amplification is visible |
| SSRF via user-controlled host | Hosts come from the target, never the call; no call can name a host |
| SSRF via redirect | One redirect, same host, re-checked |
| Credential in a log | Credentials are sealed config; headers are never audited |
| A module reaching a system it should not | Declared edges; boot refuses the undeclared |
| Response floods memory | `max_response_bytes` per target |
| Egress inside a transaction | Refused, with the sanctioned shape in the message |

### Compatibility

Purely additive. An app that installs nothing keeps today's behaviour, including
today's escape hatches — an existing `# arch-allow-no-raw-outbound-http` marker
stays valid and stays budgeted. The migration path for an app that adopts is
mechanical and is worth writing as a guide topic: move the URL to
`environment.schema.json`, declare the target in the composition root, declare the
edge on the module, replace the client call.

### Tests

- Unit: target validation, path templating and encoding refusals, redirect policy,
  breaker transitions, timeout propagation, transaction refusal.
- Architecture: both new rules, over violation and compliant fixtures.
- Integration: a `respx`-style transport double asserting exactly one attempt for a
  non-idempotent call, three for an idempotent 5xx, zero after the breaker opens.
- Security: the SSRF suite the webhooks capability already has, re-run against the
  shared resolver so the two cannot drift.
- Audit: a call produces exactly one audit record, and the record contains the
  template and not the interpolated path (asserted on a path carrying a fake
  identifier).

### Out of scope

- An async client. The persistence seam is synchronous by recorded decision
  (ADR 0072); an async egress would be the first half of an async app and belongs
  with that decision, not ahead of it.
- gRPC, GraphQL, SOAP. One protocol, and the rest are the application's business or
  a later socket.
- A service registry / discovery. A target's address is configuration; discovery is
  the deployment's job and R4 is where it would become legible.
- Response caching. `CacheStore` exists; a caching egress is a composition an app
  can make, and a cache policy per target is a second control-plane surface for a
  benefit no consumer has named.

---

## 4. R2 — the event relay: `emit` that crosses a process

**Status:** unbuilt · **Tier B** · **Kind:** the application's business, with one
security invariant (consumer idempotency) · **Runtime applicability:** `required`.

### Problem

`dispatch_in_process` is the only dispatcher. The durable variant persists an
outbox row and drains it with a worker that runs *in-process* handlers, so `emit`
crosses a process boundary only through a shared database and never a network. A
handler can even reach the producer's open transaction through
`current_event_session()` — which is exactly why there is no dual write, and
exactly what a cross-service bus cannot offer.

An application split across two deployables therefore has no event mechanism at
all. It has webhooks (outbound push to a *configured* URL, with a signature and a
retry) and it has a scheduled reconcile. Neither is a bus.

### Design

**Keep the outbox as the producer. Add a relay and a consumer.** The seam already
proves itself swappable — `OutboxJobQueue` and `outbox_event_dispatcher` changed no
call site — so the relay is a third backend, not a redesign.

```
producer app                                    consumer app
┌──────────────────────────┐                    ┌──────────────────────────┐
│ service.create()         │                    │ terp relay consume       │
│   └ emit(session, event) │                    │   ├ verify + dedupe      │
│      └ outbox row        │  broker topic      │   └ dispatch_in_process  │
│ COMMIT ───────────────┐  │  ───────────────▶  │        └ handlers        │
│ terp relay publish ◀──┘  │                    │           └ own COMMIT   │
└──────────────────────────┘                    └──────────────────────────┘
   one transaction, no dual write                 dedupe + handler in one txn
```

1. **`terp-cap-relay` publishes drained outbox rows.** It is a *second consumer* of
   the outbox worker's claim loop, not a parallel drainer: a row of kind `event`
   whose definition is marked `external=True` is published to the broker and marked
   `dispatched` in the same finalize the local dispatch already uses. At-least-once
   is unchanged and the existing retry / dead-letter path is unchanged.
2. **An event that crosses an app boundary is a versioned contract, and is declared
   as one.** `EventDefinition` gains `external: bool` and `version: int`. Only an
   external event is published; the relay refuses to publish an undeclared or
   internal one (fail closed). The set of external events is exported as
   `events.json` beside `openapi.json` — the same publish-the-contract discipline
   §12.2 of the design doc already applies to the API — so a consumer generates or
   validates against a declared payload shape instead of trusting a producer.
3. **The consumer deduplicates in the handler's own transaction.** This is the
   non-negotiable half, and it is the flaw in the naive version of this idea: the
   relay gives at-least-once *delivery*, and only the consumer can give
   at-least-once *effect*. `terp-cap-relay` therefore ships a `ConsumedMessage`
   table — `(source, message_id)` unique, `received_at`, `outcome` — and the
   consume path inserts that row **in the same transaction as the handlers' writes**.
   A duplicate hits the unique constraint, the transaction rolls back, and the
   message is acknowledged without re-running the effect. Without this the relay is
   a footgun with a nice API; with it, the guarantee an app gets is the one it
   already has locally.
4. **Envelope.** `EventEnvelope` plus: `message_id` (the outbox row id — a natural,
   already-durable dedupe key), `source` (the producing app's declared id),
   `event`, `version`, `occurred_at`, `traceparent` (R3), `tenant_id`, and the
   originating `actor_id` **only as an on-behalf-of reference** (R5) — never as an
   authorization claim, because a claim that crosses a trust boundary without a
   signature is decoration.
5. **Ordering is not promised.** Per-key ordering is available where the broker
   offers it (a partition key derived from `tenant_id` + aggregate id) and is
   opt-in per event. Saying this in the ADR matters more than the feature: a
   consumer that assumes ordering it was never promised is the second most common
   distributed-system bug after the missing dedupe.
6. **Schema evolution is additive-only, enforced.** A published `events.json` is
   checked against the previous release the way the API contract is: a removed field
   or a narrowed type on an `external` event fails the build. A breaking change ships
   as `version: n+1` alongside `n` until every consumer has moved.
7. **Broker adapters follow the jobs precedent.** `terp-cap-relay-redis` and
   `terp-cap-relay-servicebus` are thin `RelayTransport` implementations; the core
   relay knows publish, subscribe, ack, nack and dead-letter, and nothing else. The
   first adapter ships with the capability; the second proves the seam, exactly as
   ADR 0046 did for Celery.

### Enforcement (the quadruple)

| Layer | Control |
|---|---|
| Control plane | The event catalog gains `external` / `version`; the safe default is `external=False` — an event is local unless someone says otherwise |
| Runtime, fail-closed | Publishing an undeclared or internal event raises; a consumer receiving an unknown event or an incompatible version dead-letters rather than dropping; a missing `ConsumedMessage` table fails the boot of a consumer |
| Build-time | `backend/external_events_are_versioned` (an `external=True` definition without a `version` is refused) and the contract-drift check over `events.json` |
| Escape hatch | `# arch-allow-external-events-are-versioned: <reason>`, budgeted |

### Failure modes

| Failure | What the design does |
|---|---|
| Duplicate delivery | `ConsumedMessage` unique key, in the handler's transaction |
| Consumer down | Broker retains; outbox already marked dispatched — the relay's promise ends at the broker, and that boundary is documented |
| Poison message | Bounded attempts, then dead-letter with the envelope and the error |
| Producer schema change | Additive-only check; version bump for a break |
| Broker unreachable | The outbox row stays pending and retries with the existing backoff — no message is lost because nothing was marked dispatched |
| Consumer assumes ordering | Documented as unpromised; opt-in partition key where it matters |
| Tenant leakage across apps | `tenant_id` travels; the consumer's own tenancy applies on write, never the message's claim |

### Compatibility

Additive. `external` defaults to `False`, so every existing event stays local and
every existing app is byte-identical. An app adopting the relay adds a capability,
a broker, and a consumer process; it changes no `emit` call site — the promise
ADR 0008 made and ADR 0045 kept.

### Tests

- The outbox conformance suite, extended: a published row is finalized exactly once.
- Duplicate delivery of the same `message_id` runs the handler once (the sharp test).
- Crash between handler commit and broker ack → redelivery → dedupe holds.
- Contract drift: a removed field on an external event fails the build.
- Adapter parity: the same suite runs against both transports.

### Out of scope

- Exactly-once delivery. It does not exist; the design buys exactly-once *effect*
  and says so.
- A message-schema registry service. `events.json` is a published artifact, like
  the OpenAPI document. A registry is infrastructure an app may add.
- Cross-app sagas / orchestration. The primitives (jobs, leases, outbox, relay)
  compose into one; a saga engine is a product, not a control.

---

## 5. R3 — trace context, end to end

**Status:** unbuilt · **Tier B** · **Kind:** legibility ·
**Runtime applicability:** `not-applicable` (there is no rule to enforce; this is
plumbing, and its absence is a missing feature rather than a violation).

### Problem

Structured JSON logs with request-ids ship by default (ADR 0005) and the request-id
travels into background work: the `JobEnvelope` carries `actor_id`, `tenant_id` and
`request_id`, and the Celery adapter round-trips all three through the broker so a
job's writes stay stamped. `docs/DEPLOYMENT.md` states plainly that OpenTelemetry
wiring is on the roadmap.

So correlation survives the one boundary Terp built for and dies at every other:
nothing is read from an inbound request, nothing is written to an outbound call, and
two Terp deployables share no identifier at all.

### Design

**One context, four propagation points, and an exporter nobody is required to run.**

1. **W3C trace context, in and out.** The middleware that already mints the
   request-id parses inbound `traceparent` / `tracestate`, or starts a new trace,
   and binds both alongside the request-id in the existing context vars. The
   request-id stays: it is the human-readable handle in logs and in the error
   envelope, and a trace-id is not a substitute for it. Every log record gains
   `trace_id` and `span_id`.
2. **Four propagation points, all of which already exist as seams:** the request
   middleware (in), `egress` (out, R1), the `JobEnvelope` (already carries
   `request_id`; add `traceparent`), and the relay envelope (R2).
3. **`terp-cap-otel` is where the dependency lives.** `terp.core` takes no
   OpenTelemetry dependency — the kernel's layer-0 discipline forbids it and the
   library's release cadence is not ours to inherit. The capability installs an
   exporter and instruments the four points plus SQLAlchemy; without it, trace ids
   are generated, propagated and logged, and nothing is exported. That is a useful
   product on its own: correlated logs across services with no collector to run.
4. **Telemetry fails open.** This is the one place in Terp where fail-open is
   correct, and the ADR should say why rather than leave it to be discovered: a
   fail-closed exporter converts an observability outage into an application
   outage, which inverts the reason for having it. Exporter errors are counted and
   logged once per interval, never raised.
5. **Sampling is configuration, and the default is parent-based.** A service that
   honours its caller's sampling decision produces complete traces; a service that
   samples independently produces confetti.

### Enforcement (the quadruple)

This item is the one place the quadruple is *deliberately incomplete*, and the ADR
must say so rather than manufacture a rule: there is no invariant a build-time test
could check that is not already checked (nothing in an app authors a span), and no
fail-closed control that would be right. What ships is the control-plane registry
(`TelemetryConfig` with a safe default of *generate and propagate, export nothing*)
and the tests. **An item that cannot fill the quadruple is normally rejected under
§1.1; this one is admitted because it is not a control — it is instrumentation of
controls that already exist.** That distinction is worth carrying into the ADR,
because it is the exception someone will later cite for a proposal that does not
deserve it.

### Failure modes

| Failure | What the design does |
|---|---|
| Collector down | Fail open; counted, logged once per interval |
| Trace header injection from an untrusted caller | A public route starts a new trace rather than trusting the inbound one; internal callers are trusted per target |
| Cardinality explosion | Path *templates* as span names, never interpolated paths — the same rule R1 applies to audit |
| PII in span attributes | An attribute allowlist; the redaction filter that already covers logging extends to spans |
| Performance | Sampling defaults, and the exporter runs on its own thread with a bounded queue |

### Compatibility

Additive. An app that installs nothing gains `trace_id` in its logs and loses
nothing.

### Tests

- An inbound `traceparent` is continued, not replaced.
- A job run under the worker carries the enqueuing request's trace.
- An `egress` call sends a `traceparent` whose parent is the current span.
- A public route ignores an inbound trace header.
- Span names are templates (asserted against an interpolated path).

### Out of scope

Metrics and profiling. Traces first, because the gap this closes is a *causal*
one; a metrics facade with no named consumer is a second surface to maintain.

---

## 6. R4 — the deploy-unit declaration

**Status:** unbuilt · **Tier B** · **Kind:** legibility contract ·
**Runtime applicability:** `not-applicable` (a declaration is source; the runtime
never reads it — ADR 0110 decision 5's boundary, kept).

### Problem

`workbench.json` (ADR 0110) describes **one compose file** for the **development**
loop, and its ADR is explicit that it must never be consulted for the production
profile. ADR 0111 decision 6 then split deployment into three layers and named
layer 2 — legibility — as existing. For a single deployable it does. For a fleet
there is no vocabulary at all: nothing says which unit is the app, which owns which
migrations, how to health-check each, or what a rollback is.

The consequence is the one ADR 0111 decision 3 predicts: the tool loses a feature
and the app is never told.

### Design

**`deployment.json` at the project root, defined in `terp-spec`, truth-checked by
`terp verify`, never gating.**

```json
{
  "schemaVersion": 1,
  "units": [
    {
      "id": "api",
      "role": "api",
      "healthPath": "/health/ready",
      "livenessPath": "/health/live",
      "migrations": ["app", "audit", "access"],
      "env": ["DATABASE_URL", "SECRET_KEY", "LEDGER_BASE_URL"],
      "dependsOn": ["db"]
    },
    { "id": "worker", "role": "worker", "command": "terp jobs worker", "dependsOn": ["db"] },
    { "id": "db", "role": "datastore", "stateful": true, "backup": "nightly-snapshot" }
  ],
  "rollback": { "strategy": "redeploy-previous-image", "migrations": "expand-contract" }
}
```

Four rules, all inherited from ADR 0110 rather than invented:

1. **Partial description, not a whitelist.** A unit the declaration does not name is
   not the tool's business. An unknown `role` is information, not an error — with
   ADR 0110 decision 3's one boundary: an unknown role carrying a field a tool
   resolves *by role* is red, because that field has no reader.
2. **Truth about self, never conformance.** Red is: a declared unit that does not
   exist in the profile it names; a `migrations` entry naming a label no package
   owns; a `healthPath` the app does not serve; a declared env name the profile
   never passes. Never red: three APIs, no frontend, a unit we have never heard of,
   a topology nobody predicted.
3. **`unmanaged: true` with a required reason** turns the check off and makes any
   tool report honestly that it cannot drive the deploy.
4. **The words live in the spec** (ADR 0111 decision 5), beside
   `layout-declaration.schema.json` and `assurance-profile.schema.json`, so a Studio
   and a framework on different versions still agree on what an application said.
   The enforcement stays in the framework.

**One genuinely new capability this unlocks**, and it is the reason the item is
worth its release: `migrations` per unit makes the *migrate-then-serve* ordering
machine-readable, so a tool can run the one-shot for exactly the histories a unit
owns rather than assuming one migrate job for the whole app. That is the first
thing a second deployable needs and the first thing a Kubernetes rendering would
need.

### Enforcement

| Layer | Control |
|---|---|
| Control plane | The schema in `terp-spec`; absence is legal and means "not described" |
| Runtime, fail-closed | None, deliberately — this is layer 2, and gating it would take away the freedom layer 3 protects |
| Build-time | `terp verify --only deployment`, joining the standard profile |
| Escape hatch | `unmanaged: true` + reason |

### Compatibility

Additive; absence passes. Where `workbench.json` and `deployment.json` overlap
conceptually they stay separate files, because ADR 0110 decision 5 refuses a
declaration whose `compose.file` names a deployment profile, and that refusal is
still right: dev is retryable and deployment is not.

### Tests

Each red case above as a fixture; each never-red case as a fixture that passes; the
`unmanaged` escape; and a schema round-trip in both the framework's reader and the
spec's own tests, since two programs read these bytes.

### Out of scope

Rendering the deployment (Helm, Terraform, a PaaS manifest). ADR 0062 defers those
until a consumer proves the need, and a declaration is what makes the eventual
renderer *possible* without deciding it now.

---

## 7. R5 — audience-scoped service tokens and on-behalf-of

**Status:** unbuilt · **Tier A** · **Kind:** security invariant ·
**Runtime applicability:** `required`.

### Problem

ADR 0088 made a machine a first-class subject kind, so a program authenticates as
itself rather than as a human with a fake email. What it did not do — correctly, at
the time — is let a token cross a service boundary. A token is minted for one app
and carries no audience, so a second deployable presented with it either trusts a
token that was not issued for it or requires a second credential. And when service
A calls service B on behalf of a user, B's audit records the integration; the person
disappears at the hop.

ADR 0114 decision 3 lists this as the third cost of a split and notes it is
recoverable only with a claim that does not exist.

### Design

**One claim pair, one endpoint, and no second authorization path** — the constraint
ADR 0088 imposed on itself.

1. **`aud` becomes mandatory and checked.** Every token gains an audience: the app
   that minted it, by declared app id. A validator refuses a token whose `aud` is
   not this app's. Existing single-app deployments are unaffected because the
   minter and the validator are the same app; the check is a no-op until there are
   two.
2. **`POST /auth/token/exchange`** — a service principal presents its own token and
   asks for one scoped to a named audience. It receives a short-lived token
   carrying `aud: "<callee>"`, its own `sub`, and, when the exchange is made during
   a user-originated request, `act: { sub: <user id>, kind: "user" }` — the
   delegation claim, in the shape RFC 8693 already standardised, because inventing
   a private claim for a solved problem is how two services stop interoperating.
3. **Exchange is granted, never assumed.** A service principal carries an explicit
   audience allowlist. An exchange for an ungranted audience is refused and
   audited. This is the same deny-by-default posture as a `Policy`; it is not a new
   authorization path, it is the existing grant model applied to a new subject.
4. **The callee stamps two fields, never one.** `actor_id` is the delegated user
   when `act` is present, and `via_id` is the service principal. Collapsing them
   loses either who did it or how it arrived; keeping both means an audit query can
   answer "everything this person caused, including through integrations" and
   "everything that arrived through this integration", which are different
   questions and both get asked.
5. **`act` is a record, not a grant.** The callee authorizes the *service
   principal's* permissions, not the user's. A delegated token that widened
   authority would be a confused-deputy generator. If an app genuinely needs the
   user's own authority downstream, that is a second design (a scoped, consented
   delegation) and is out of scope here — named so it is not assumed.
6. **Lifetime and revocation.** Exchanged tokens are short-lived (minutes) and
   non-refreshable; revoking the service principal invalidates the ability to
   exchange, and the short TTL bounds the rest. Terp's revocation-enforcing
   provider (ADR 0031) already re-validates every request, so a revoked principal
   stops mid-flight in the minting app.

### Enforcement (the quadruple)

| Layer | Control |
|---|---|
| Control plane | App id + audience allowlist per service principal; safe default is an empty allowlist (exchange is impossible until granted) |
| Runtime, fail-closed | Wrong `aud` → 401; ungranted audience → 403 + audit; `act` present without a service `sub` → refused; missing app id in production → `BootError` |
| Build-time | `backend/tokens_declare_audience` — a composition root minting tokens without an app id is refused |
| Escape hatch | Budgeted, for a single-app deployment that deliberately mints audience-less tokens during migration |

### Failure modes

| Failure | What the design does |
|---|---|
| Token replay at another service | `aud` check |
| Confused deputy | `act` grants nothing; the service principal's own permissions apply |
| A user's authority silently widening | Explicitly out of scope; `act` is a record |
| Stolen exchanged token | Minutes-long TTL, non-refreshable |
| Audit says "integration" | `actor_id` + `via_id`, both stamped |
| Clock skew across services | Bounded leeway, documented, and the same value in both directions |

### Compatibility

Additive with one deliberate ratchet: `aud` becomes mandatory at mint time, which
is invisible in a single-app deployment (minter == validator) and is exactly the
check a second deployable needs. Apps upgrade by setting an app id; the
`BootError` in production makes forgetting it loud rather than silent.

### Tests

- A token minted for app A is refused by app B.
- An exchange for an ungranted audience is refused and audited.
- A delegated write lands with `actor_id` = user and `via_id` = service.
- A delegated token does not grant the user's permissions (the confused-deputy test).
- Revoking the service principal stops exchange within one request.

### Out of scope

- User-consented delegation with the user's own authority (named above).
- mTLS / SPIFFE workload identity. A deployment may add it beneath this; it is not
  a substitute for an application-level audience, and it is infrastructure.

---

# Part II — Application reach

---

## 8. R6 — the aggregation seam

**Status:** unbuilt · **Tier A** · **Kind:** security invariant ·
**Runtime applicability:** `required`. **This is the highest-value item in the
program.**

### Problem

`BaseService` gives declared `filterable` fields, declared `sortable` fields,
`default_sort`, offset and keyset pagination, and a `count` for the page envelope.
There is no aggregation of any kind.

So every "total by month", "count by status", "sum per region" screen — the most
requested screen in line-of-business software — is a hand-written query in an app
module. And the platform's read discipline makes that *specifically dangerous*
rather than merely untidy:

- Row scope is not a filter a developer remembers; it is composed centrally into
  `base_query()`, which "row scope is applied **centrally and cannot be dropped by a
  service**" and which `base_query_not_overridden` protects.
- `reads_use_base_query` refuses `select(Model)` on a `SoftDeleteMixin` /
  `TenantScopedMixin` model in a module *precisely because* a bespoke read drops
  that scope.
- The runtime backstop (`apply_row_scope` on the request session) covers
  single-entity reads.

An aggregate is neither a `select(Model)` the rule recognises nor a single-entity
read the backstop covers. A `select(func.sum(Invoice.amount)).group_by(...)` written
in a module is the one shape that can slip between all three controls — and its
failure mode is not a wrong number on a dashboard. **It is one tenant's revenue
appearing in another tenant's chart**, silently, forever, with every rule green.

That is why this item is Tier A and a security invariant rather than a feature: the
seam exists to close a hole, and the chart in §9 is a consequence.

### Design

**Declare measures and dimensions on the service, exactly as filters and sorts are
declared, and compose them onto `base_query()` as a subquery so scope is
structurally preserved.**

```python
from terp.core import BaseService, Measure, Dimension, TimeBucket, Page, Bucket

class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
    model = Invoice

    filterable = (FilterField("status", Invoice.status),)
    sortable = (SortField("issued_at", Invoice.issued_at),)

    measures = (
        Measure("total", "sum", Invoice.amount),
        Measure("invoices", "count", Invoice.id),
        Measure("largest", "max", Invoice.amount),
    )
    dimensions = (
        Dimension("status", Invoice.status),
        Dimension("customer", Invoice.customer_id),
        TimeBucket("month", Invoice.issued_at, granularity="month"),
    )
    max_groups = 500        # the cardinality cap; the class default is 1000
```

```python
@router.get("/summary", response_model=Page[Bucket])
def invoice_summary(
    pagination: PaginationDep,
    session: SessionDep,
    service: InvoiceService = Depends(get_service),
    status: str | None = None,
) -> Page[Bucket]:
    return service.aggregate(
        session,
        measures=("total", "invoices"),
        group_by=("month", "status"),
        filters={"status": status},
        pagination=pagination,
        order_by="-month",
    )
```

Eight decisions, each closing one way this goes wrong.

1. **Composition, not construction.** `aggregate()` builds
   `select(dimensions..., measures...).select_from(self.base_query().subquery())`.
   Row scope, soft delete and `business_filters` are inside the subquery, so they
   cannot be omitted — there is no code path in which a module supplies the FROM
   clause. This is the whole design; everything else is guard rails around it.
2. **Only declared names.** `measures=` and `group_by=` take names resolved against
   the class declarations; an undeclared name raises the same typed error an
   undeclared filter raises today. A module cannot aggregate a column its service
   did not expose, which is also what keeps a summary endpoint from leaking a
   column the read DTO excludes.
3. **A closed set of aggregate functions** — `sum`, `count`, `count_distinct`,
   `min`, `max`, `avg`. Not a callable, because a callable is an injection surface
   and an un-reviewable one. `avg` returns a `Decimal` and the DTO says so; float
   money is a bug generator.
4. **Time bucketing is the framework's, not the app's.** `TimeBucket` renders
   `date_trunc` on PostgreSQL and `strftime` on SQLite from one declaration, so a
   report is not the place an app discovers dialect parity. Granularity is a closed
   set (`hour`, `day`, `week`, `month`, `quarter`, `year`) and the bucket is
   computed in **UTC** with an optional declared `tz` — a monthly total silently
   computed in the server's timezone is the classic finance-report defect.
5. **Every aggregate is paginated and capped.** The response is `Page[Bucket]`, so
   the existing envelope and its caps apply — offset pagination over a declared
   ordering, not keyset: a bucket has no stable unique key to cursor on, so
   offering `list_by_cursor`'s shape here would be a promise the data cannot keep.
   Beyond pagination, `max_groups` bounds
   the *group cardinality*: the seam runs a cheap cardinality probe and raises a
   typed `AggregationTooBroadError` (422, with the offending dimension named) rather
   than streaming a million rows into memory. Grouping by a high-cardinality column
   is a mistake the platform can catch, and the message tells the author to add a
   filter or a time bucket.
6. **`Bucket` is a typed DTO, not a dict.** `Bucket(dimensions: Mapping[str, str |
   None], measures: Mapping[str, Decimal | int])`, with `null` as an explicit
   dimension value rather than a missing key — a chart that silently drops the
   "unassigned" bucket is a wrong chart.
7. **Aggregates are reads and are audited as reads.** No `_after_write`, no OCC, no
   audit rows. Where the app declares read controls (`declared_read_controls_are_forwarded`),
   they forward here too.
8. **A cross-module aggregate is not in this design.** Joining two modules' tables
   in one aggregate is a module boundary violation wearing a report's clothes.
   The sanctioned shape is one aggregate per module composed in the UI, or a
   declared edge (ADR 0087) and a service method on the owning module. Saying this
   plainly is part of the deliverable, because "just one join" is how the module
   boundary erodes.

### Enforcement (the quadruple)

| Layer | Control |
|---|---|
| Control plane | `measures` / `dimensions` / `max_groups` on the service, empty by default — a service aggregates nothing until it says so |
| Runtime, fail-closed | Undeclared measure or dimension → typed error; cardinality over `max_groups` → 422; the subquery composition makes scope non-optional |
| Build-time | **`backend/aggregates_use_declared_measures`** — a module constructing `func.sum` / `func.count` / `func.avg` / `func.min` / `func.max` over a model column outside the seam is refused. This is the rule that closes the hole; without it the seam is merely a convenience |
| Escape hatch | `# arch-allow-aggregates-use-declared-measures: <reason>`, budgeted — and the guide topic says what an author must then re-establish by hand (the scope predicate), because an escape hatch that does not name its obligation is a trap |

New spec catalog entry, `static-portable`, `runtime.applicability: required` (the
seam refuses undeclared names at runtime; the build-time rule is the earlier half).
Corpus: a violation sample (a hand-built `func.sum` on a tenant-scoped model) and a
compliant sample (the declared seam), which flips `corpus` and drops the rule from
`PENDING.json`.

### Failure modes

| Failure | What the design does |
|---|---|
| **Cross-tenant leak in a report** | Impossible through the seam: the FROM clause is `base_query()` |
| Soft-deleted rows counted | Same mechanism |
| Unbounded group cardinality | Probe + `max_groups` + typed 422 |
| Timezone-wrong month totals | UTC by default, declared `tz`, one implementation |
| Dialect drift dev→prod | `TimeBucket` renders per dialect; the PostgreSQL lane tests it |
| Float money | `Decimal` in the DTO and in the column type |
| Missing "unassigned" bucket | `null` is a value, not an absence |
| An app escaping the seam | The build-time rule; and the hatch is budgeted and named |

### Compatibility

Purely additive: a service that declares no measures is unchanged, and the new rule
fires only on code that does not exist yet in a compliant app. Apps that *already*
hand-rolled an aggregate will see the new rule fire — which is the point — and can
adopt the seam or budget the hatch. That is the one case in this program where an
existing app sees a new red, and it is a red worth seeing; the CHANGELOG entry must
say so in those words.

### Tests

- Scope: an aggregate run as tenant A never includes tenant B's rows — asserted
  directly, and again through a service that tries to override `base_query`
  (already refused) and through `business_filters`.
- Soft delete: deleted rows excluded.
- Every aggregate function against both dialects; `Decimal` types preserved.
- `TimeBucket` boundaries at DST and at year end, in UTC and in a declared tz.
- Cardinality cap: 422 naming the dimension.
- Undeclared measure / dimension → typed error.
- Architecture: the new rule over violation and compliant fixtures.
- PostgreSQL lane: the whole suite, since bucketing and casting are dialect-shaped.

### Out of scope

- A query language or an ad-hoc "pivot builder" API. Declared names only; a
  self-service analytics tool is a product, and a database view plus a read-only
  model (R11) is the escape for a genuinely bespoke report.
- Window functions, `HAVING`, nested aggregates. Named as the likely second
  request; deliberately not in v1, and each would need its own containment argument.
- Materialisation / caching of aggregates. `CacheStore` exists; a materialised
  report is an app's decision until two apps ask.

---

## 9. R7 — the chart primitive and the data palette

**Status:** unbuilt · **Tier C** · **Kind:** the application's business, made
governed · **Runtime applicability:** `not-applicable`. **Depends on R6, and that
dependency is what makes it admissible.**

### Problem

`@terpjs/react-core` has no visualisation of any kind. ADR 0099 surveyed eighteen
candidate components and refused thirteen on the rule *a component that cannot name
a consumer in this framework is declined* — a bar that, applied to charts, could
never be cleared, because the framework had nothing to plot.

R6 changes that: `Page[Bucket]` is a framework surface whose only sensible
rendering is a chart, and a framework endpoint shape is exactly the consumer ADR
0099 asks for. This is not an exception to the test; it is the test passing.

Meanwhile the alternative is worse than it looks. An app that needs a chart today
builds it in `frontend/src/components/` (outside the module glob the styling rules
run on) or pulls a charting library — either way with hardcoded colours, against
**five** shipped themes, and outside the WCAG contract `token-pairs.json` and
`tokens.contrast.test.js` hold every other pixel to.

### Design

**A small, dependency-free SVG renderer over a declared series shape, in the
palette, with a mandatory accessible equivalent.**

```tsx
<Chart
  kind="bar"                       // line | bar | area | stacked-bar
  data={summary.items}             // Bucket[] from R6, unmodified
  x={{ dimension: "month", label: msg.month }}
  series={[{ measure: "total", label: msg.revenue }]}
  format="currency"
  height="md"                      // a step, not a pixel count
  emptyState={<EmptyState … />}
/>
```

1. **No runtime dependency.** The icon layer is the precedent: Terp ships a
   dependency-free glyph set rather than an icon package, for the same reasons
   (bundle, supply chain, and a version cadence that is not ours). A line, a bar, a
   stacked bar and an area are `polyline`, `rect` and `path` over two scales. What
   makes charts hard is *taste and accessibility*, not geometry, and a library
   supplies neither.
2. **It consumes `Bucket[]` directly.** No adapter, no massaging. If the data did
   not come from R6 it must be shaped the same way — which is a feature: it keeps
   the aggregate honest (paginated, capped, scoped) rather than inviting a
   client-side reduction over an unbounded list.
3. **A new token family: `--color-data-1` … `--color-data-8`**, defined in every
   theme, ordered for categorical use (adjacent entries maximally distinguishable),
   with a `--color-data-N-contrast` for a label placed on the mark. They enter
   `token-pairs.json` — marks against surfaces under `nonTextPairs` (3:1, SC
   1.4.11), axis and value labels under `textPairs` (AA) — so
   `tokens.contrast.test.js` holds all five themes and `contrast` to its AAA floor.
   A palette that is not in that file is a palette nobody checks.
4. **Colour is never the only encoding.** A series carries a label, and where two
   series must be told apart at a glance the renderer varies pattern as well as
   hue (dash for line, hatch for area/stacked). Eight percent of men cannot use the
   hue-only version, and a platform that holds every text pairing to AA cannot ship
   a chart that fails colour-blind readers.
5. **Every chart has a data equivalent, and it is not optional.** The chart renders
   `role="img"` with a generated `aria-label` summarising series and range, plus a
   visually-hidden `<table>` of the same rows — or, with `showTable`, a visible
   `DataView variant="embedded"` beneath it. An SVG that a screen reader cannot read
   is not accessible because it has a title.
6. **Formatting goes through the locale seam.** `formatNumber` / `formatDate` and
   the `UiText` discipline apply to every tick and label; a chart is one of the
   easiest places to leak an untranslated string or an OS-locale number, and the
   i18n rules already run over all of `src/**`.
7. **Layout contract.** `Chart` enters the overview- and detail-body slot lists in
   `layout-contract.json`, and `Sparkline` (the second, deliberately tiny component)
   is admitted inside `HubCard` and inside a `DataView` cell, which is where a trend
   belongs beside a number.
8. **Refused inside the item:** pie and donut (angle is the least accurate
   perceptual encoding, and the request is nearly always a bar); 3-D anything;
   entry animation by default (`prefers-reduced-motion` and the fact that a chart
   that moves on load is harder to read); a second table; and a general "plot
   anything" escape prop, which would be a chart library with extra steps.

### Enforcement (the quadruple)

| Layer | Control |
|---|---|
| Control plane | The data-token family in the token source; every theme must define it or the theme test fails |
| Runtime, fail-closed | The layout-contract runtime check already refuses a component outside its slot; a `Chart` whose `series` names a measure absent from the data throws a directive error rather than rendering an empty box |
| Build-time | The `terp/layout-contract` lint half; `tokens.contrast.test.js` over the new pairs; `token-pairs.json` completeness |
| Escape hatch | The existing `// terp-allow-*` markers; an app wanting a different chart uses R10's component zone, knowingly |

### Failure modes

| Failure | What the design does |
|---|---|
| Unreadable in one of five themes | Tokens per theme + contrast tests over the pairs |
| Colour-blind readers | Pattern varies with hue; labels always present |
| Screen-reader users get nothing | Mandatory table equivalent, not a toggle |
| Unbounded client-side data | Consumes `Page[Bucket]`; the cap is server-side (R6) |
| Untranslated tick labels | The i18n rules already run app-wide |
| Misleading axis | Bar charts start at zero and the prop to change it does not exist |

### Compatibility

Additive; a new export and a new token family. Existing themes gain tokens (a theme
that omits them fails its completeness test, which is how the ratchet works).

### Tests

- Render tests per chart kind, including one-point, zero-point and null-dimension data.
- Contrast: every data token against every surface, in all five themes.
- Accessibility: axe over each kind; the table equivalent present and correct.
- Locale: ticks formatted in the app's locale, not the browser's.
- Layout contract: `Chart` in a hub body is refused; in an overview body it passes.

### Out of scope

Maps, network graphs, Gantt, calendars-as-charts. Each is a genuine instrument and
belongs to R10's component zone until two applications ask for the same one.

---

## 10. R8 — the search seam

**Status:** unbuilt · **Tier B** · **Kind:** the application's business ·
**Runtime applicability:** `required` (undeclared field → refused).

### Problem

Reads offer declared `filterable` equality/comparison fields and declared sorts.
There is no text search — no full-text, no ranking, no highlighting, no
multi-column match. Every application past a few thousand rows asks for a search
box, and the only paths available are a hand-written `ILIKE` chain (unindexed, and
subject to the same scope hazard as R6) or `no_dynamic_sql`'s escape hatch to build
a `to_tsquery` string, which is exactly the shape that rule exists to refuse.

PostgreSQL is the verified production dialect and has full-text search built in.
The gap is a seam, not a technology.

### Design

**Declare searchable fields on the service; the framework owns the query
construction, the index, and the dialect difference.**

```python
class CustomerService(BaseService[Customer, CustomerCreate, CustomerUpdate]):
    model = Customer
    searchable = (
        SearchField("name", Customer.name, weight="A"),
        SearchField("city", Customer.city, weight="B"),
        SearchField("notes", Customer.notes, weight="D"),
    )
    search_config = "simple"   # or a language configuration; declared, never user input
```

```python
results = service.search(session, q="rotterdam harbour", pagination=pagination)
# -> Page[Customer], ordered by rank, composed on base_query()
```

1. **Composed on `base_query()`, like everything else.** A search that could
   escape row scope would be R6's leak with a different SQL shape.
2. **The query text is a bound parameter, always.** The seam builds
   `websearch_to_tsquery(:config, :q)` — a parameterised call that accepts human
   input safely (quoted phrases, `or`, `-negation`) and cannot become SQL. No
   string is ever concatenated, so `no_dynamic_sql` stays satisfied without a hatch.
3. **The index is generated, not hand-written.** `terp.migrations` gains
   `add_search_index(table, fields, config)`, which emits a generated `tsvector`
   column plus a GIN index in the module's *own* migration — so table ownership and
   the one-owning-history rule are untouched. A `searchable` declaration with no
   matching index fails `terp verify` (a drift check in the same family as
   `tables_have_migrations`), because an unindexed full-text search on a large table
   is an outage waiting for growth.
4. **SQLite is a declared, dev-only fallback.** `LIKE` over the same fields, no
   ranking. It is documented as dev-only in the same sentence as the ADR 0069
   support matrix, and the PostgreSQL lane is where search is actually tested. A
   fallback that pretends to be equivalent is worse than one that says it is not.
5. **Rank is the default sort and can be overridden by a declared sort.**
   `ts_rank_cd` with the declared weights; ties broken deterministically by id, so
   pagination is stable.
6. **Highlighting is opt-in and server-side** (`ts_headline`), returned as a
   separate field on the DTO rather than injected into the value — the frontend
   refuses HTML injection sinks, so a snippet with markup would be unusable and
   dangerous. The snippet is plain text with declared match offsets; the frontend
   renders the emphasis.

### Enforcement

| Layer | Control |
|---|---|
| Control plane | `searchable` / `search_config` on the service, empty by default |
| Runtime, fail-closed | `search()` on a service with no `searchable` raises; an undeclared config value is refused |
| Build-time | The index-drift check; `no_dynamic_sql` continues to cover hand-rolled attempts |
| Escape hatch | Budgeted, as ever |

### Failure modes

| Failure | What the design does |
|---|---|
| Injection through the search box | `websearch_to_tsquery` with a bound parameter |
| Cross-tenant results | `base_query()` composition |
| Sequential scan at scale | Index required, drift-checked |
| Unstable pagination | Deterministic tie-break |
| XSS through a highlight | Plain text + offsets, never markup |
| A dev-only fallback shipping to production | ADR 0069's dialect guard already refuses SQLite in production |

### Compatibility, tests, out of scope

Additive; a service without `searchable` is unchanged. Tests: injection corpus,
scope, ranking order, stable pagination, index drift, and the PostgreSQL lane.
Out of scope: fuzzy/trigram matching, synonyms, faceting, and an external search
engine — each is a second design, and faceting in particular is R6 wearing a
different hat and should reuse it rather than grow a parallel path.

---

## 11. R9 — model calls, streaming, and long-running work

**Status:** unbuilt · **Tier B** · **Kind:** the application's business ·
**Runtime applicability:** `required` for the budget control.
**Mostly not a new subsystem — deliberately.**

### Problem

A large share of new application requests now include at least one model-backed
feature, and Terp supplies none of the four things such a feature needs: a way to
call the provider (R1's gap), a way to stream tokens to the browser, a way to run
something slow without holding a request, and a way to bound what it costs. For a
platform whose premise is that people build applications through an agent, an
application that cannot itself call a model is a pointed limitation.

### Design

**Three of the four already exist. The work is composition, one new control, and
saying which shape is sanctioned.**

1. **The call is `egress` (R1) with a target of kind `model`.** No separate HTTP
   path, no provider SDK in `terp.core`, no vendor coupling in the kernel: a model
   endpoint is an HTTP dependency with an unusual latency profile, and R1's
   controls — declared target, mandatory timeout, SSRF guard, sealed credentials,
   no-call-inside-a-transaction, egress audit — are exactly the controls it needs.
   `kind="model"` adjusts three defaults: a much longer read timeout, retries off by
   default (a partially-generated response is not idempotent), and the token-budget
   hook below.
2. **Slow work is a job, and that is not a workaround.** The jobs seam already runs
   post-commit with actor/tenant/request-id bound and a `RetryPolicy`; a generation
   that takes 40 seconds belongs there for the same reason a sync does. The request
   returns an identifier; the browser follows the result.
3. **Streaming is the realtime capability.** A job streams chunks into a declared
   `RealtimeChannel` and the browser consumes it with `useRealtimeChannel`, which
   already mints a short-lived one-use ticket, validates every payload against the
   channel's type guard, and never touches a raw transport. Two additions make it
   fit a token stream rather than an event feed: a **chunk envelope**
   (`{ seq, delta, done }`) so a client can order and terminate, and per-channel
   backpressure so a slow consumer does not accumulate unboundedly in the broker.
   ADR 0108 already established that a stream needs a shutdown; a token stream needs
   the same discipline.
4. **The new control: a token budget.** `ModelBudget` in the control plane — per
   principal, per tenant, and per target, over the same shared-store shape as the
   throttle (`ThrottleStore` semantics, Redis adapter, fail-closed). A call that
   would exceed the budget is refused *before* it is made, with a typed error. This
   is the one genuinely new thing, and it is Tier B rather than A because the
   values are a business decision even though the shape is not. Without it, the
   first cost incident is discovered on an invoice.
5. **Prompts and responses are redacted in audit by default.** The egress audit
   record carries target, model, token counts, latency and status — never the
   prompt, never the completion. A per-target `retain_content=True` (with a reason)
   opts in for a debugging window, because "log the prompt" is how customer data
   ends up in a log aggregator forever.
6. **Vector storage is deferred, not refused.** `pgvector` on the verified dialect
   would be a capability with a table, an index and a nearest-neighbour read seam —
   a real design, and a straightforward one. It is deferred under §14's amended
   test with the trigger named: **two applications asking**. Recording the trigger
   is the point; "deferred with no criterion" is how a gap becomes permanent.

### Enforcement

| Layer | Control |
|---|---|
| Control plane | `ModelBudget` with a safe default of *no budget configured → calls refused in production* (fail closed on cost, the same posture as a missing durable audit sink) |
| Runtime, fail-closed | Budget exceeded → typed error; budget store error → refused; the R1 transaction and timeout controls apply unchanged |
| Build-time | R1's rules cover the call site; no new rule is needed, and inventing one would be surface for its own sake |
| Escape hatch | `ModelBudget.unlimited(reason=...)`, budgeted and greppable |

### Failure modes

| Failure | What the design does |
|---|---|
| Runaway cost | Pre-call budget check on a shared store |
| A generation holding a request thread | Jobs; and R1 refuses the call inside a transaction |
| Prompt injection reaching a tool | Out of scope here — an application concern the platform cannot generically bound, and saying so is more honest than a token control |
| Customer data in logs | Redacted by default, opt-in with a reason |
| A stream that never ends | Chunk envelope with `done`, plus ADR 0108's shutdown discipline |
| Provider outage | R1's breaker |

### Compatibility, tests, out of scope

Additive. Tests: budget enforcement across two instances against a shared store;
a job streaming to a channel with ordered chunks and a terminal frame; audit
redaction asserted on a prompt containing a marker string. Out of scope: prompt
management, evaluation harnesses, agent frameworks, and model routing — all
products, none controls, and each one a thing an application can build on the
seams above.

---

## 12. R10 — screens that are not a record: the instrument archetype and the component zone

**Status:** unbuilt · **Tier B** · **Kind:** legibility contract ·
**Runtime applicability:** `required` (the archetype check already exists and is
extended).

### Problem

Two facts sit uncomfortably together.

First, `buildAppRouter` refuses an unframed routed view at runtime, and the
archetypes are `Page`, `OverviewPage`, `DetailPage`, `HubPage`, `FormPage`,
`SettingsPage` and `SplitPage` — a vocabulary for records and collections. There is
no shape for a screen that is *one interactive instrument*: a scheduling board, a
calendar, a floor plan, a map, a diagram editor, a drawing surface.

Second, the styling and element rules run on `**/modules/**` while only the
localization rules run over all of `src/**`. So `frontend/src/components/Board.tsx`
may already use `className`, its own stylesheet, raw elements — and, more
uncomfortably, raw `fetch`, `innerHTML` and `eval`, because the *security* rules
live in the module block too.

That is a hole, not a design. It is also the only thing making bespoke UI possible
today. Both halves need fixing at once: give the instrument a legible frame, and
make the zone where bespoke components live a governed place rather than an
accident.

### Design — two halves, one change

**(a) `InstrumentPage`: a fourth archetype for a screen that is one instrument.**

```tsx
<InstrumentPage
  instrument="scheduling-board"      // required, declared, and legible
  title={msg.planning}
  parents={[…]}
  actions={<PageActions … />}
>
  <SchedulingBoard … />              {/* the app's own component */}
</InstrumentPage>
```

It keeps the page band — breadcrumb trail, the single `h1`, badges, description,
actions — so navigation, titling and the shell contract are unchanged. Its body
slot is *deliberately unconstrained*, and the `instrument` name is the price of
that freedom: a tool reading the layout declaration can see that this screen is not
a collection, and therefore that its own collection-shaped affordances do not
apply. That is ADR 0111's bargain exactly — arbitrary is fine, silent is not.

**(b) The component zone: declared, and governed for security only.**

```json
// frontend/layout-contract.json
{
  "componentZone": {
    "paths": ["src/components/**"],
    "reason": "app-authored instruments: scheduling board, floor plan"
  }
}
```

Inside a declared zone, the boundary config applies:

| Rule family | Inside the component zone |
|---|---|
| `no-dom-html-injection`, `no-eval`, `no-unsafe-href`, `no-unsafe-target-blank` | **enforced** — these are security invariants and have no business varying by directory |
| `generated-client-only` (no raw `fetch` / `XHR` / `WebSocket` / `EventSource` / `sendBeacon`) | **enforced** — one typed egress path is a security property, not a styling preference |
| `no-cross-module-imports`, `no-deep-imports` | **enforced** |
| `no-inline-styling`, `no-style-imports`, `token-styled-elements` | **relaxed**, because drawing an instrument is what the zone is for |
| `no-untranslated-ui`, `locale-catalogs-complete` | **enforced** (they already run app-wide) |
| `layout-contract` | not applicable — a zone component is not a routed view |

Undeclared paths keep today's behaviour exactly. So this change **adds**
enforcement (the security rules now reach code that escaped them) and **documents**
a relaxation that already existed silently. Both halves are improvements, and the
second is the one that makes the first acceptable.

Three supporting decisions:

1. **The zone gets the tokens, not a free hand.** A zone component may use
   `className` and a stylesheet, and the token stylesheet is available to it, so
   `var(--color-fg-accent)` is the path of least resistance and a hardcoded hex is
   a choice. A lint *warning* would be a severity dial, which ADR 0059 refuses; a
   guide topic and a good default are the honest tools here.
2. **A zone is bounded and reasoned.** `paths` and `reason` are required; a zone
   covering `src/**` fails the check, because a zone that covers everything is the
   absence of a boundary.
3. **The escape-hatch budget counts zone components.** Not as violations — they are
   not violations — but as a declared count in `escape-hatch-budget.json`, so the
   ratchet shows an app's bespoke surface growing. What gets measured gets
   discussed at review time.

### Enforcement

| Layer | Control |
|---|---|
| Control plane | `componentZone` in `layout-contract.json`, absent by default; `instrument` required on the archetype |
| Runtime, fail-closed | `buildAppRouter` accepts `InstrumentPage` as a frame; an `InstrumentPage` without an `instrument` name throws a directive error |
| Build-time | The lint's file-scope config reads the declared zone; a zone covering all of `src` fails; the archetype enters the layout contract |
| Escape hatch | The existing markers, unchanged |

### Failure modes

| Failure | What the design does |
|---|---|
| The zone becomes the app | Bounded paths, required reason, counted in the budget |
| Security rules escaped via `src/components` | Closed — this change extends them there |
| An instrument that is really a list | Review; the archetype names it, so the mistake is visible in a diff |
| A bespoke component that ignores themes | Tokens available and documented; not enforced, and honestly so |

### Compatibility

Additive and, for the security rules, a genuine (correct) tightening for any app
that already has bespoke components — the CHANGELOG must lead with that, not bury
it. An app with no `componentZone` sees the security rules extend to `src/**`
unchanged in kind, so the migration is: adopt the rules, or declare the zone (which
does not exempt them anyway).

### Tests, out of scope

Tests: the lint applies the right rule set per path; an undeclared path keeps
today's behaviour; the archetype is accepted by the router and refuses a missing
name; the layout contract admits it. Out of scope: shipping a calendar, board, map
or editor component. Each stays an application's until §14's amended test counts
two askers — and when one does cross that line, it enters the catalog properly
rather than as a zone component blessed after the fact.

---

## 13. R11 — data Terp does not own

**Status:** unbuilt · **Tier B** · **Kind:** the application's business ·
**Runtime applicability:** `required` for the write refusal.

### Problem

`BaseTable` mandates a UUID id, `created_at` / `updated_at` and an OCC `version`;
`table_models_use_base_table` refuses a bare model; the migration subsystem assumes
each table has exactly one owning history; and the boot guard refuses a schema
behind the code. Together these are the reason Terp's guarantees hold — and they
mean an application cannot *read* a table it does not own without leaving the
governed zone entirely.

The shapes this blocks are ordinary enterprise ones: a reporting view maintained by
a DBA; a legacy table with an integer or composite key that another system writes;
a materialised view; a table in the same database owned by a different application.
Today the sanctioned answer is the sidecar package (`terp guide package-boundaries`)
— correct for a whole subsystem, disproportionate for reading one view.

### Design

**Two new model bases, one read-only service, and an explicit statement that Terp
does not own these tables.**

```python
from terp.core import ExternalTable, ReadOnlyService

class LedgerBalance(ExternalTable, table=True):
    __tablename__ = "vw_ledger_balance"      # a view maintained elsewhere
    __external__ = ExternalSource(owner="ledger-dba", managed=False)

    account_id: str = Field(primary_key=True, max_length=64)
    balance: Decimal
    as_of: datetime

class LedgerBalanceService(ReadOnlyService[LedgerBalance]):
    model = LedgerBalance
    filterable = (FilterField("account_id", LedgerBalance.account_id),)
```

1. **`ExternalTable` is not `BaseTable` and does not pretend to be.** No managed id,
   no timestamps, no OCC. It is exempt from `table_models_use_base_table` by
   *declaration* rather than by escape hatch — which is the difference between a
   designed exemption and a budgeted violation.
2. **Migrations explicitly disclaim ownership.** An `ExternalTable` is excluded
   from autogenerate, from the model/migration drift check, and from
   `assert_migrations_current`. `table_ownership_is_not_split` is unaffected because
   no package claims it. The framework's promise here is precise: *we will not
   create, alter or drop this table, and we will not tell you it is up to date.*
3. **Reads are the default and writes are refused.** `ReadOnlyService` exposes
   `get` / `find` / `list` / `list_by_cursor` / `search` / `aggregate`, all composed
   on a `base_query()` that still applies `business_filters` and any declared row
   scope the app configures. There is no `create` / `update` / `delete` to call.
4. **Writing to an unowned table is possible, loudly.** `UnmanagedWriteService`
   exists, requires a `reason=`, is budgeted, and its docstring states what the app
   takes on: no OCC (nothing versions the row), no auto-audit of *another system's*
   concurrent writes, and no migration safety. An application that must write to a
   legacy table is not served by a refusal; it is served by a path whose costs are
   printed on it.
5. **Scope must be declared, because the framework cannot infer it.** A tenant
   column on a foreign table is a *claim*, not a construction. `ExternalTable`
   therefore requires an explicit `row_scope=` declaration (or an explicit
   `row_scope=None` with a reason) — no silent default, because a silently
   unscoped external read is R6's leak arriving through a different door.
6. **Views are first-class.** A read-only model over a database view is the
   sanctioned answer to a bespoke report that R6's declared measures cannot express
   — which is what keeps R6 from growing a query language.

**Dialects, in the same breath.** ADR 0069's matrix stands: SQLite for dev/test,
PostgreSQL verified in a CI lane, anything else behind
`DB_ALLOW_UNVERIFIED_DIALECT=true`. What this item adds is honesty about that third
tier: publish the migrations-conformance suite as something an application can run
against *its* dialect, so "unverified" becomes "verified by you, with our suite"
rather than a shrug. That is a small change to packaging and a large change to what
an enterprise client can be told.

### Enforcement, failure modes, tests

| Layer | Control |
|---|---|
| Control plane | `ExternalSource` on the model; required `row_scope` declaration |
| Runtime, fail-closed | No write methods; `UnmanagedWriteService` requires a reason; a missing `row_scope` declaration fails at class definition |
| Build-time | `backend/external_tables_declare_scope`; the drift check learns to skip external models |
| Escape hatch | `UnmanagedWriteService(reason=…)`, budgeted |

Failure modes: an unscoped external read (refused at definition); a drift check
falsely failing on a foreign table (excluded by declaration); an app assuming OCC
on a foreign row (there is no `version` column and the DTO says so); a view
disappearing under the app (a startup probe reports it as unavailable rather than
failing every request with a driver error).

Tests: read/scope/aggregate over an external model; drift check ignores it; writes
absent from the service surface; the unmanaged path audited; a PostgreSQL-lane test
over a real view.

### Out of scope

Reading a *second database*. That is a second engine and a second transaction
boundary — it belongs with the read-replica seam the design doc already reserves,
and it is the point at which the sidecar is genuinely the right answer.

---

## 14. R12 — public and consumer-facing surfaces

**Status:** unbuilt · **Tier A** · **Kind:** security invariant ·
**Runtime applicability:** `required`.

### Problem

The backend half is already designed: `Policy.public(reason=…)` declares an
unauthenticated module, `public_modules_are_read_only` refuses a mutating route
under it unless the policy opts in with `Policy.public_write(reason=…)`, and the
boot refuses the mismatch. That is a good control.

The frontend has no matching notion. The shell is an authenticated application
shell — `RequireAuth`, `LoginView`, the user menu pinned to the sidebar, nav
resolved against `/me` — and every routed view must render an archetype whose band
assumes a signed-in context. An app with a public tracking page, a shared read-only
link, a status page, or an unauthenticated intake form has to leave the shell.

Worse, the two halves cannot currently disagree *visibly*: a module may declare a
public backend policy while every route that would use it sits behind the auth
gate, or the reverse, and nothing reconciles them.

### Design

1. **`public: true` on `ModuleRoute`, fail closed.** A route is authenticated
   unless it says otherwise — the same default as a `Policy`. `buildAppRouter`
   mounts public routes outside `RequireAuth`; everything else is unchanged.
2. **`PublicShell` + `PublicPage`.** A minimal frame: brand, theme and language
   controls, an optional sign-in call to action, no sidebar, no user menu, no `/me`
   dependency. `PublicPage` is the archetype (the router's unframed-view refusal
   still applies), with the same band contract minus the parts that need a session.
3. **The two halves are reconciled by a check, not by convention.**
   `terp verify` compares the frontend manifest's public routes against the
   backend's public policies and reports a mismatch: a public route calling a
   module with no public policy is a broken page; a public policy no public route
   uses is an unauthenticated surface nobody meant to expose. This is the
   `routes-drift` family the verify profile already runs, extended one step, and it
   is the item's real security value.
4. **A public module implies a shared throttle store.** An unauthenticated endpoint
   with a per-instance rate limit in a multi-replica deployment has an effective
   limit multiplied by the replica count. So declaring any public policy sets
   `require_shared_throttle_store` in production, fail closed. This is one line and
   it prevents the most predictable incident on the list.
5. **Public reads still scope.** A public module's service composes `base_query()`
   like any other; "public" removes authentication, never row scope. The guide topic
   must say this in the first paragraph, because the intuition runs the other way.

### Enforcement, failure modes, compatibility

| Layer | Control |
|---|---|
| Control plane | `public` defaults to `false` on routes; public policies already require a reason |
| Runtime, fail-closed | Public route outside the gate only when declared; implied shared-throttle requirement; the existing public-write boot refusal |
| Build-time | `frontend/public-routes-are-declared` + the cross-surface drift check |
| Escape hatch | Budgeted, per the existing public-write hatch |

Failure modes: an accidentally public route (declared, checked, and visible in a
diff); rate-limit dilution (implied shared store); a public page leaking
cross-tenant rows (scope unchanged); a search engine indexing an app page (the
public shell emits `noindex` unless the app opts out, because the default should be
the safe one).

Compatibility: additive; absent declarations mean everything stays authenticated.

### Out of scope — and this one matters commercially

**Server-side rendering and SEO are refused.** A Terp app is a Vite SPA served
same-origin behind nginx (ADR 0062). SSR would add a Node runtime to the deployment
profile, a second rendering path for every component, and a hydration contract the
conformance suite would have to cover on every stack — for a benefit that applies
to *marketing* pages, which are not what this platform is for. The honest advice,
which belongs in the guide topic rather than in a backlog: **a public marketing
site should not be a Terp application.** A public *application* surface — a
tracking page, a portal, an intake form — is what R12 serves, and it does not need
SSR. Static prerendering of a handful of public routes at build time remains an
application's own choice and needs nothing from the framework.

---

## 15. R13 — the governed-zone map

**Status:** unbuilt · **Tier B** · **Kind:** legibility contract ·
**Runtime applicability:** `not-applicable`. **Smallest item here; possibly the
highest ratio of value to effort.**

### Problem

Which rules apply where is currently folklore assembled from three places: the
backend rules resolve a file's module by looking for a `modules/` path segment; the
frontend boundary config runs the security, styling and client rules on
`**/modules/**` and only the localization rules on `**/src/**`; and the sidecar
pattern lives in a guide topic. Nothing states the map, so two reasonable people —
or two agent sessions — hold different models of it, and the difference only shows
up when something that should have been refused ships.

This is the platform's own diagnosis applied to itself: a protection whose absence
is invisible cannot be opt-in, and a boundary nobody can read is not a boundary.

### Design

1. **Write the map down**, in `AGENTIC_PLATFORM_DESIGN.md` and in a new
   `terp guide zones`: the four zones (framework packages; app modules — the
   governed zone; app shared code — governed for security, and after R10 that is
   true on both surfaces; the sidecar — governed by declared import contracts), and
   for each, the rule families that apply and why.
2. **Make it answerable per file**: `terp check --explain <path>` prints which
   rules apply to that file, which zone it is in, and why. For an agent this is
   worth more than the prose: it converts a question that is currently answered by
   reading three configs into one command, and it cannot drift from the
   implementation because it *is* the implementation.
3. **Make the sidecar legible**: `workbench.json` services and R4's deployment units
   gain `gate: "terp" | "external"`, so a tool can tell that a unit is deliberately
   outside the gate rather than missing from it.

### Enforcement, compatibility, tests

No new runtime control and no new refusal — this item removes silence, not
capability, which is exactly ADR 0111 decision 2's test. `--explain` is covered by
tests asserting the printed set equals the set actually applied (the property that
keeps documentation and behaviour from diverging), and the guide topic is held to
the config by a test in the same family as the existing env-seam parity test.

---

## 16. R14 — governance: how a gap becomes a decision

**Status:** proposal · **Kind:** governance · no runtime component.

### Problem

ADR 0099 declined thirteen components on the rule *a component that cannot name a
consumer in this framework is declined*, and that rule is right about what it was
written for: it stops a framework accreting surface nobody uses, and §1 of that ADR
shows it working in both directions.

Applied to an application platform indefinitely, it has a structural consequence.
An application's need is never a consumer *in this framework*. So the component
surface can only grow toward what the framework already does, and the framework
does records and collections. Every item in Part II that touches UI fails this test
as written — including R7, which passes only because R6 manufactures a
framework-side consumer.

The same asymmetry applies beyond components: a capability nobody in the framework
needs is exactly what an application needs.

### Decision proposed

1. **Amend the test:** *a component or capability that cannot name a consumer in
   this framework, **or two independent applications that asked for it**, is
   declined.* Two, not one, because one application's need is a feature request and
   two is a pattern — and because the platform team should not be the first to
   discover which of the two it is.
2. **Make the asking countable.** A lightweight ledger — a labelled issue per
   request, with the *shape* asked for, not the component name — so "two
   applications asked" is a query rather than a memory. Recorded requests do not
   expire, and the second one flips the item to a design task.
3. **Ask for the socket, not the plug** (ADR 0111 decision 4). The ledger's template
   asks what the application must *declare* and what it must *not* be able to do,
   because that is what turns a request into a seam that serves the next twenty
   applications rather than a component that serves one.
4. **Refusals stay written down.** ADR 0099's practice — a refusal that lives only
   in someone's head gets re-proposed every few months — extends to this program:
   §17 exists so the eight refusals are arguable on the merits rather than
   re-derived.

**If this amendment is rejected**, R7, R10 and R12 are rejected with it, and the
platform's answer to a client asking for a dashboard is the escape hatch. That is a
legitimate choice; it should be made deliberately rather than inherited from a test
written for a different question.

---

# Part III — What this program refuses

Eight things were considered and are refused. Each is written down for the reason
ADR 0099 gives: a refusal that lives only in someone's head gets re-proposed every
few months, and each re-proposal costs the same survey again. Each entry names the
sanctioned alternative, because a refusal without one is just a closed door.

### 17.1 Asynchronous persistence

Persistence is synchronous `Session` by recorded decision (ADR 0072), and an async
variant would land as a *parallel* seam, never a rewrite. Making it parallel means
two service base classes, two session seams, two sets of every rule that mentions a
session, and a doubled conformance surface — for a benefit that is real only for
workloads dominated by concurrent slow I/O.

**Alternative:** a request that fans out to slow dependencies belongs in a job
(post-commit, retried, audited), and R1 refuses the call inside a transaction
anyway. If an application is *dominated* by that shape, it is a gateway, and a
gateway is a sidecar.

### 17.2 A non-relational primary store

Document, graph and time-series stores each dissolve a guarantee the platform
sells: OCC needs a version column, audit needs a transaction, the scope predicate
needs a query the framework composes, and migrations need a schema.

**Alternative:** PostgreSQL's own JSONB for document-shaped columns (already
usable); the sidecar for a genuinely different store; and R11 for reading something
another system owns.

### 17.3 High-volume ingest

Every mutation through `BaseService` is audited, actor-stamped and OCC-versioned.
That is the product. It is also precisely wrong at thousands of rows per second,
and a "bulk path" that skips those controls is not a fast path through Terp — it is
a hole with a flag on it.

**Alternative:** the sidecar writes to its own table with its own contract, and the
Terp app reads it through R11. The boundary is declared with import-linter and the
sidecar is legible per R13.

### 17.4 Offline-first client sync

Client↔server reconciliation is a distributed-systems product (conflict
resolution, causality, partial application), not a seam. The `sync` capability is
server↔external-system and deliberately different.

**Alternative:** none supplied; an application that genuinely needs it should know
that before choosing the platform, which is why this belongs in the guide topic
R13 produces rather than in a backlog.

### 17.5 Micro-frontends / a federated shell

One shell, one contract, one identity authority is the design (ADR 0114 decision
1). Module federation would multiply the token contract, the locale catalogs, the
theme surface and the layout contract across independently deployed bundles, and
every conformance guarantee would become per-bundle.

**Alternative:** several typed clients in one shell (ADR 0041 already allows an app
to generate its own paths), or a genuinely separate product consuming the same
contract — the split §12.3 of the design doc already sanctions.

### 17.6 Server-side rendering

See R12's out-of-scope. A public *marketing* site should not be a Terp application.

### 17.7 A query language or pivot builder

R6 deliberately takes declared names only. A self-service analytics surface is a
product with its own security model (it is, definitionally, a way to ask questions
nobody enumerated), and it would re-open the exact hole R6 closes.

**Alternative:** a database view plus a read-only model (R11), which puts the
bespoke question in a reviewable artefact a DBA owns.

### 17.8 A second table component, and the rest of ADR 0099's thirteen

Unchanged. R10's component zone is where an application's bespoke surface lives,
and §14's amended test is how one of those becomes a framework component — by
being asked for twice, not by being convenient once.

---

# Part IV — Sequencing, release mechanics, and risk

## 18. Waves

**Wave 1 — the two holes and the map.** R6 (aggregation), R7 (chart), R1 (egress),
R13 (zone map), R14 (governance). R6 and R1 are the two places where the *absence*
of a seam actively pushes authors toward a dangerous or ungoverned path, so they
come first on safety grounds rather than demand. R13 and R14 are small and unblock
the conversation about everything else.

**Wave 2 — what wave 1 makes possible.** R3 (tracing, needs R1's call site to
propagate into), R9 (models, is R1 plus a budget), R8 (search), R10 (instrument +
component zone), R12 (public surfaces).

**Wave 3 — the independently large.** R2 (relay), R5 (tokens), R4 (deployment
declaration), R11 (external data).

Nothing in wave 2 or 3 is blocked by anything other than its stated dependency, so
the waves are an ordering, not a gate.

## 19. Release mechanics

- **Lockstep.** Every backend distribution and frontend package carries the same
  version and publishes from the same tag (ADR 0063); `test_release_versions`
  enforces it. A new capability is a new distribution *at the current version*, and
  adding one is a release event even when nothing else changed.
- **Spec first, then framework, then spec CI again.** The two CIs are circularly
  coupled: terp-spec's `certify-against-reference` job runs framework main against
  the catalog, while the framework's gate installs the *pinned published* terp-spec.
  So each new rule in this program follows the documented order — push the spec,
  release it, bump both pins in the framework, then re-run spec CI. R6, R1, R2, R5,
  R11 and R12 each carry catalog entries; **budget one spec release per wave**, not
  per rule.
- **Corpus and ratchets.** Every new rule ships violation and compliant samples,
  flipping its `corpus` flag and dropping it from `corpus/PENDING.json`. Where a
  checker deliberately cannot catch a form (R1's dynamically-built path assigned to
  a variable three functions away is the obvious one), the residual is recorded in
  `corpus/RESIDUALS.json` rather than over-claimed.
- **Guide topics are part of the deliverable, not documentation debt.** `terp guide
  egress`, `guide reporting`, `guide search`, `guide zones`, `guide public`,
  `guide external-data`. The generated `AGENTS.md` points at them; an agent that
  cannot find the sanctioned path will use the escape hatch.
- **One CHANGELOG entry per item**, written in the repository's voice: the friction
  first, the mechanism second, the migration last — and never naming a downstream
  application, per `AGENTS.md`.

## 20. Risks, honestly

| Risk | Assessment | Mitigation |
|---|---|---|
| **Surface growth outruns the team** | The real one. Fourteen items is several releases of maintenance, forever | The waves are independently valuable; stopping after wave 1 leaves the platform strictly better and coherent |
| R6's new rule fires on existing apps | Intended, and the only new red in the program | Lead the CHANGELOG with it; ship the guide topic in the same release |
| R1's transaction refusal is unpopular | Likely — it will look like the framework being difficult | The error message carries the reason and the fix; the opt-out takes a reason string, so it is available and visible |
| R10's zone becomes the app | The failure mode that would quietly undo the platform | Bounded paths, required reason, counted in the budget, and reviewed |
| R7 without R14 | Would be an exception to a written test, which corrodes the test | Land R14 first, or drop R7 |
| Charts, search and models are each a rabbit hole | Yes | Each item's *Out of scope* is the contract; the second request goes to R14's ledger, not into the release |
| Two capabilities per wave inflate the install surface | Real but bounded | Every capability here is opt-in and discovery is profile-shaped (`capability_names`) |

## 21. What a reviewer is being asked to decide

1. **R14's amendment** — yes or no. It gates R7, R10 and R12, and it is a change to
   how this platform decides, not just what it builds.
2. **Wave 1's contents** — R6 and R1 are argued here as safety work rather than
   features. If that argument does not land, they are ordinary features and the
   ordering is open.
3. **The eight refusals** — each is a closed door with an alternative behind it, and
   §17 is written to be disagreed with in a review rather than re-litigated in six
   months.
4. **Whether anything here should instead be an application's.** The honest test
   from §1.1 applies to this document too: an item that cannot ship the quadruple is
   a product decision. R3 is admitted as an explicit exception and says so; if a
   reviewer thinks another item is in the same position, that is the most useful
   finding this document could get.

## 22. Open questions

- **R2's broker.** The first adapter should be the one the platform's own
  deployments will actually run; that choice is not made here, and it should be made
  by whoever operates them rather than by this document.
- **R6's cardinality probe.** A cheap `COUNT(DISTINCT …)` is itself a scan on a
  large table. A sampled estimate, a `LIMIT`-based probe that fails on overflow, or
  a declared-only cap are three options with different failure modes; the design
  above assumes the second and it deserves a benchmark before it is fixed.
- **R7's renderer.** Dependency-free is argued from the icon-layer precedent, and a
  chart is a larger thing than a glyph. If a pinned, tree-shakeable library turns out
  to cost less than the maintenance of four chart kinds, that is a legitimate reversal
  — but it must then meet the CSP and theming constraints, not just the feature list.
- **R11's dialect tier.** Publishing the conformance suite for an application to run
  against its own dialect is proposed here as packaging; whether the platform then
  *supports* what an application certifies is a commercial question, not a technical
  one.
- **Where the ledger lives.** R14 needs somewhere countable that outlives a
  conversation; a labelled issue queue is the obvious answer and is not this
  document's to choose.
