# ADR 0051 — Outbound webhooks: signed, SSRF-guarded delivery on the jobs/outbox seam

- Status: Accepted
- Date: 2026-06-30
- Phase: Phase 2 capabilities / production-readiness backlog ("Outbound webhooks /
  notifications", STATUS) — the first *consumer* built purely on the async ports.
- Number: 0046–0050 are taken by the parallel jobs-engine-adapter line (the celery
  adapter is ADR 0046); the outbound-webhooks capability is this **0051**.
- Relates to: ADR 0043 (the jobs seam — the typed `enqueue` + `JobDefinition` this rides),
  ADR 0045 (the durable outbox — the retry / dead-letter mechanism it leans on), ADR 0008
  (the event bus + `@subscribe` — the trigger), ADR 0007 / 0027 (`terp-cap-audit` — the
  table-owning-capability + packaged-migration precedent the delivery log mirrors), ADR
  0029 (`OwnedMixin` — the per-row write gate on subscriptions), ADR 0020 / 0037 / 0040
  (`response_model_not_table_model` + `schemas_exclude_sensitive_fields` — the secret never
  leaves the boundary), ADR 0038 (the re-entrant `enter_write_unit` the delivery log rides),
  ADR 0006 (the Tier-A "quadruple")
- Defers to later ADRs: at-rest secret sealing (the §5.4 `encrypt_config` /
  `mask_config` / `decrypt_config` subsystem), subscriber-side replay windows, and a
  per-owner read-visibility predicate for subscriptions.

## Context

Terp needs to deliver **outbound webhooks** — POST a signed payload to a consumer-registered
HTTP endpoint when a domain event fires — and a webhook is the textbook example of two hard
problems the platform already has seams for: it is **background work that must survive a
crash** (so it belongs behind the jobs seam + the durable outbox, never inline in a request),
and it makes the **server issue an HTTP request to a caller-supplied URL** (so SSRF is the top
OWASP risk). This ADR ships `terp-cap-webhooks` built **only** on the shipped ports — the jobs
seam (ADR 0043), the durable outbox (ADR 0045), and the event bus `@subscribe` (ADR 0008) —
adding **no** engine and **no** `terp.core` change.

## Decision

### 1. `terp-cap-webhooks` — two tables, one entry-point router

An opt-in capability (discovered at `/api/v1/webhooks`, like `terp-cap-audit`) owning two
tables with an independent Alembic history (`alembic_version_webhooks`):

- **`WebhookSubscription`** (`BaseTable` + `OwnedMixin`): `target_url`, signing `secret`,
  subscribed `event` name, `active` — every caller `str` length-capped. Composing `OwnedMixin`
  makes the per-row write gate (ADR 0029) authorize edit / delete to the owning admin with
  **no** module code; the management router is `ADMIN`-only (webhooks are a privileged,
  SSRF-sensitive, outbound-network surface).
- **`WebhookDelivery`** (append-only, `UUIDPrimaryKeyMixin` like `AuditEvent` /
  `OutboxMessage`): one immutable row per delivery **attempt** — `subscription_id` (FK-less,
  so history survives a subscription's deletion), `event`, `outcome`, `response_code`,
  `attempt`, `last_error`. It is written by a tiny store function that rides
  `enter_write_unit()` under a governed, budgeted `# arch-allow-*` marker, exactly like the
  audit sink / outbox store at the base of the write stack.

### 2. The external call lives in the job handler (post-commit, on a worker)

A `WEBHOOK_DELIVER` `JobDefinition` (declared in the consumer's `JobCatalog`) carries the
subscription id + a per-attempt-stable `delivery_id` + the event name + the event's public
data (ids, not entities). Its handler runs **post-commit, on the outbox worker** — never in
an `_after_write` hook, which would dual-write the business row and a remote call. The handler
**re-loads** the live subscription (so the target / secret never ride the wire), **re-checks**
the target against the SSRF denylist and **pins the connection to the validated IP**
(DNS-rebinding defense), **signs** `timestamp.body` (HMAC-SHA256, keyed by the stored secret)
and POSTs it with a strict timeout, a bounded payload size, and **no redirect following**; it
records a `WebhookDelivery` and, on a non-2xx
or transport error, **propagates** so the `RetryPolicy` + outbox worker retry with backoff and
dead-letter. A deterministic terminal outcome (a removed / inactive subscription, an
SSRF-blocked target, an oversized body) records its row and returns **without** raising, so a
retry that could not help is never wasted. Because `run_job` opens the handler at write-depth
0, the recorded row commits immediately — so a failure attempt is **both** persisted **and**
re-delivered.

### 3. The trigger: `@subscribe` enqueues atomically with the business write

A consumer wires the capability's generic fan-out to a catalog event with the eventbus
`@subscribe` decorator. When the event fires — synchronously, inside the business write's
transaction (the in-process dispatcher) — the handler enqueues one `WEBHOOK_DELIVER` job per
matching active subscription **on the producer's session**, so each durable outbox row commits
**atomically** with the business write (no dual-write); a rollback drops both. The worker then
delivers each off-request.

For the handler to reach the producer's session, the eventbus gains one small, additive seam:
`current_event_session()`, a `ContextVar` bound by `dispatch_in_process` around its synchronous
fan-out — the event-handler analogue of the request-scoped `audit_actor_ctx` / `request_id_ctx`
(idiomatic, not ambient magic). The webhooks capability itself stays decoupled from the event
bus: its fan-out takes the session **explicitly** (`enqueue_webhook_deliveries(session,
envelope)`); only the thin app glue reads `current_event_session()`. The capability depends on
only `terp-core` and `httpx`.

### 4. Security (OWASP), enforced and tested

- **SSRF is the top risk.** `validate_webhook_target` fails closed: it requires `https`,
  resolves the host, and rejects the target if **any** resolved address (or an IP-literal
  host, or an IPv4-mapped IPv6) is in a denied range — private / loopback / link-local /
  carrier-grade-NAT / benchmarking / cloud-metadata (`169.254.169.254`) / IPv6 ULA — via an
  explicit, **testable** denylist (`is_denied_address`) layered with the `ipaddress` `is_*`
  flags. It is enforced **twice**: at create / update (422 at the boundary) **and** in the
  delivery handler immediately before the POST — which then **pins the connection to that
  validated address** (a repointed httpx request that keeps the hostname's TLS SNI /
  certificate verification and `Host` header), so the socket cannot be re-resolved to a
  private IP between the check and the connect (closing the DNS-rebinding TOCTOU). Redirects
  are not followed (a 3xx is a recorded failure, never chased to a possibly-disallowed host).
- **The signing secret never leaves the boundary.** It is supplied on create (an input body)
  and stored, but **no `*Read` DTO serializes it** — enforced by the
  `schemas_exclude_sensitive_fields` rule (the cap is run through the full arch harness) **and**
  a runtime test. At-rest sealing awaits the §5.4 secrets subsystem (`encrypt_config` /
  `mask_config` / `decrypt_config`, a tracked backlog item); the property enforced **today** is
  API-boundary non-disclosure — the secret is write-only and used server-side only to sign.
- **Signatures are timestamped (replay-resistant).** Each POST carries an
  `X-Terp-Webhook-Timestamp` header and an `X-Terp-Signature` HMAC-SHA256 over `timestamp.body`
  (keyed by the subscription secret), so a receiver bounds the age and rejects a replayed
  capture — a valid signature is not indefinitely reusable.
- A strict outbound **timeout** + a bounded outbound **payload size**, and per-row **write
  authorization** (`OwnedMixin`).
- `httpx` is a dependency of **this capability only** (the delivery handler); an app module
  never imports it — background delivery flows through the typed `enqueue` chokepoint.

## Consequences

- A consumer registers a subscription, declares `WEBHOOK_DELIVER` in its `JobCatalog`, wires
  `@subscribe(<event>)` to the fan-out, and composes the durable `OutboxJobQueue` — then a
  domain event fires → a delivery row is written atomically → `terp jobs worker` signs and POSTs
  it → retries / dead-letters on failure. No `terp.core` change ⇒ no vendored-core mirror touch.
- The example app dogfoods it end-to-end: an admin registers a webhook for `notes.note.created`;
  creating a note enqueues a durable delivery atomically, and the worker delivers a signed POST
  (proven with a mocked sender), recorded in the read-only delivery log. The example and every
  capability stay arch-clean; the example budget stays `{}`.
- The eventbus `current_event_session()` seam is additive and backward-compatible (existing
  handlers are untouched); it is the generic way any app folds transactional follow-up work into
  an event's transaction.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the `WEBHOOK_DELIVER` `JobDefinition` + `JobCatalog`
   entry, the injectable `WebhookSender` seam (httpx default), and the explicit SSRF denylist.
2. **Fail-closed runtime** — `validate_webhook_target` rejects an SSRF / non-https target
   (boundary **and** delivery-time); the fan-out enqueues atomically on the producer's session
   (no dual-write); a failed delivery records + propagates so the outbox retries / dead-letters;
   `OwnedMixin` denies a non-owner write; the secret is never serialized.
3. **Build-time** — the capability runs through the **full `terp.arch` harness**
   (`test_capability_arch`), its only opt-outs the governed, budgeted append-only-table +
   base-of-the-write-stack `session` writes + the `_internal` write-scope reach (the same
   framework-infra markers as `terp-cap-outbox`), ratcheted by a checked-in escape-hatch budget;
   the `schemas_exclude_sensitive_fields` rule is the build-time half of the secret-non-leak
   control. The migration is exercised by the upgrade / downgrade / no-drift conformance gate,
   and the whole capability is under the 100% line-coverage gate.
4. **Budgeted escape hatch** — the capability's governed `# arch-allow-*` markers
   (`packages/backend/capabilities/webhooks/escape-hatch-budget.json`).

`tests/architecture/test_webhooks.py` is the capability gate (the SSRF denylist incl.
metadata / IPv4-mapped / DNS-rebinding, the never-leaked secret, the HMAC signature, the
atomic event → enqueue + rollback-drops-both, the worker's signed POST + recorded delivery,
the retry-then-dead-letter and network-error paths, and the deterministic skip / blocked
terminal outcomes — all with mocked HTTP). `apps/example/tests/test_webhooks_api.py` proves
the wired composition (owner-scoped admin CRUD, the boundary SSRF refusal, the non-owner 403,
and the note → signed-delivery loop). The full suite is green at 100% line coverage.
