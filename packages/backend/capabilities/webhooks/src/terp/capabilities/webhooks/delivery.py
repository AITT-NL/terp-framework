"""The ``WEBHOOK_DELIVER`` job: sign + POST one delivery, record the attempt, retry on failure.

This is the worker half of the webhook seam (the jobs design's §6 / §7): the external HTTP
call lives **here**, in a job handler that runs **post-commit, on a worker**, drained from
the durable outbox — never in an ``_after_write`` hook (which would dual-write the business
row and a remote call). The trigger (an event subscriber) only *enqueues* this job, atomically
with the business write; this handler delivers it off-request, and a failure **propagates** so
the :class:`~terp.core.RetryPolicy` + outbox worker retry with exponential backoff and
dead-letter after the attempt budget is spent.

Security controls applied on every attempt:

* an **SSRF re-check** of the target immediately before the request (DNS-rebinding defense,
  :mod:`terp.capabilities.webhooks.ssrf`);
* an **HMAC-SHA256** signature over the exact JSON body, keyed by the subscription's stored
  ``secret`` — which never leaves the server;
* a strict outbound **timeout**, a bounded outbound **payload size**, and **no redirect
  following** (a 3xx is recorded as a failure, never chased to a possibly-disallowed host).

The outbound HTTP client is the injectable :data:`WebhookSender` seam (default: ``httpx``),
so tests drive the handler with no real network I/O — and ``httpx`` is imported only here, in
this capability, never by an app module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from sqlmodel import Field

from terp.core import (
    AppError,
    BaseSchema,
    JobContext,
    JobDefinition,
    JobVisibility,
    NotFoundError,
    RetryPolicy,
)

from terp.capabilities.webhooks.models import (
    OUTCOME_BLOCKED,
    OUTCOME_DELIVERED,
    OUTCOME_FAILED,
    OUTCOME_SKIPPED,
)
from terp.capabilities.webhooks.sealing import WebhookSecretError, unseal_secret
from terp.capabilities.webhooks.service import WebhookSubscriptionService
from terp.capabilities.webhooks.ssrf import (
    PinnedTarget,
    WebhookTargetError,
    resolve_pinned_target,
)
from terp.capabilities.webhooks.store import record_delivery

# Conservative secure outbound limits (Tier-B-style knobs with safe defaults).
_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_PAYLOAD_BYTES: Final[int] = 256 * 1024  # 256 KiB cap on the signed body
_SIGNATURE_HEADER: Final[str] = "X-Terp-Signature"
_TIMESTAMP_HEADER: Final[str] = "X-Terp-Webhook-Timestamp"
_EVENT_HEADER: Final[str] = "X-Terp-Event"
_DELIVERY_HEADER: Final[str] = "X-Terp-Delivery-Id"


def _utc_now() -> datetime:
    """UTC ``now`` provider for the signature timestamp (private so tests can patch it)."""
    return datetime.now(UTC)


class WebhookDeliveryError(AppError):
    """502 — a webhook delivery attempt failed; propagated so the outbox retries / dead-letters."""

    status_code = 502
    code = "webhook_delivery_failed"
    default_message = "The webhook endpoint did not accept the delivery."


class WebhookDeliveryPayload(BaseSchema):
    """The JSON-serializable payload carried by a ``WEBHOOK_DELIVER`` job (ids, not entities).

    It carries the subscription id (the handler re-loads the live row to read the current
    target / secret — neither rides the wire), a per-attempt-stable ``delivery_id`` the
    subscriber can dedupe on, the originating event name, and the event's public ``data``.
    """

    subscription_id: uuid.UUID
    delivery_id: uuid.UUID
    event: str = Field(max_length=128)
    data: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class WebhookResponse:
    """The minimal result the handler needs from an outbound POST (the status code)."""

    status_code: int


# A sender performs the actual POST and returns a :class:`WebhookResponse`. It is injectable
# so tests drive the handler without real network I/O (mirroring the audit-sink / throttle-
# store seams); the default implementation uses ``httpx``.
WebhookSender = Callable[[PinnedTarget, bytes, dict[str, str]], WebhookResponse]


def _httpx_sender(
    target: PinnedTarget, body: bytes, headers: dict[str, str]
) -> WebhookResponse:
    """Default sender: POST to *target*, pinned to its pre-validated IP, no redirect chasing.

    The request is built from the original ``https`` URL (so the ``Host`` header + path are
    correct and TLS is verified against the hostname via the ``sni_hostname`` extension), then
    the connection is **repointed to the validated IP** — so a DNS-rebinding attacker cannot
    make the socket land on a private address after the SSRF check (closing the TOCTOU). A
    strict timeout bounds the request; redirects are never followed.
    """
    with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
        request = client.build_request(
            "POST",
            target.url,
            content=body,
            headers=headers,
            extensions={"sni_hostname": target.host},
        )
        request.url = request.url.copy_with(host=target.ip)
        response = client.send(request)
    return WebhookResponse(status_code=response.status_code)


_active_sender: WebhookSender = _httpx_sender


def set_webhook_sender(sender: WebhookSender) -> None:
    """Install the outbound HTTP *sender* (the seam tests replace with a fake)."""
    global _active_sender
    _active_sender = sender


def reset_webhook_sender() -> None:
    """Restore the default ``httpx`` sender (the test-isolation reset)."""
    global _active_sender
    _active_sender = _httpx_sender


def active_webhook_sender() -> WebhookSender:
    """The sender the delivery handler currently posts through."""
    return _active_sender


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    """``sha256=<hex>`` HMAC-SHA256 over ``timestamp.body``, keyed by the subscription *secret*.

    Binding the timestamp into the signature lets a receiver reject a **replay** of a captured
    delivery: it recomputes the HMAC over the ``X-Terp-Webhook-Timestamp`` header value and the
    raw body and bounds the age, so a valid signature is not indefinitely reusable.
    """
    signed = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


_service = WebhookSubscriptionService()


def deliver_webhook(ctx: JobContext, payload: WebhookDeliveryPayload) -> None:
    """Deliver one webhook: load the subscription, sign, POST, record the attempt.

    Runs in its own audited unit on a worker (``run_job``). A non-2xx response or a network
    error records a ``failed`` attempt and then **raises** :class:`WebhookDeliveryError`, so
    the outbox retries with backoff and dead-letters after the job's ``RetryPolicy`` budget.
    A removed / inactive subscription, an SSRF-blocked target, or an oversized payload records
    a terminal attempt and returns without raising (a retry could not help).
    """
    try:
        subscription = _service.get(ctx.session, payload.subscription_id)
    except NotFoundError:
        record_delivery(
            ctx.session,
            subscription_id=payload.subscription_id,
            event=payload.event,
            outcome=OUTCOME_SKIPPED,
            attempt=ctx.attempt,
            last_error="subscription no longer exists",
        )
        return
    if not subscription.active:
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_SKIPPED,
            attempt=ctx.attempt,
            last_error="subscription is inactive",
        )
        return

    body = json.dumps(payload.data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > _MAX_PAYLOAD_BYTES:
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_FAILED,
            attempt=ctx.attempt,
            last_error=f"payload exceeds the {_MAX_PAYLOAD_BYTES}-byte cap",
        )
        return  # an oversized payload is deterministic — do not waste retries on it

    try:
        pinned = resolve_pinned_target(subscription.target_url)
    except WebhookTargetError as exc:
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_BLOCKED,
            attempt=ctx.attempt,
            last_error=exc.message,
        )
        return  # an SSRF-blocked target is deterministic — do not retry it

    try:
        # Sealed at rest (ADR 0076): the plaintext exists only here, at signing time.
        signing_secret = unseal_secret(subscription.secret)
    except WebhookSecretError as exc:
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_FAILED,
            attempt=ctx.attempt,
            last_error=exc.message,
        )
        return  # a secret that no longer unseals is deterministic — do not retry it

    timestamp = str(int(_utc_now().timestamp()))
    headers = {
        "Content-Type": "application/json",
        _TIMESTAMP_HEADER: timestamp,
        _SIGNATURE_HEADER: _sign(signing_secret, timestamp, body),
        _EVENT_HEADER: payload.event,
        _DELIVERY_HEADER: str(payload.delivery_id),
    }
    try:
        response = active_webhook_sender()(pinned, body, headers)
    except Exception as exc:  # noqa: BLE001 - any transport error becomes a recorded, retried failure
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_FAILED,
            response_code=None,
            attempt=ctx.attempt,
            last_error=f"request error: {exc}",
        )
        raise WebhookDeliveryError(
            f"webhook request to subscription {subscription.id} failed"
        ) from exc

    if 200 <= response.status_code < 300:
        record_delivery(
            ctx.session,
            subscription_id=subscription.id,
            event=payload.event,
            outcome=OUTCOME_DELIVERED,
            response_code=response.status_code,
            attempt=ctx.attempt,
        )
        return
    record_delivery(
        ctx.session,
        subscription_id=subscription.id,
        event=payload.event,
        outcome=OUTCOME_FAILED,
        response_code=response.status_code,
        attempt=ctx.attempt,
        last_error=f"endpoint returned HTTP {response.status_code}",
    )
    raise WebhookDeliveryError(
        f"webhook delivery to subscription {subscription.id} failed with "
        f"HTTP {response.status_code}"
    )


# The typed job contract a consumer wires into its control-plane ``JobCatalog`` so the
# trigger can enqueue it (and the outbox worker resolve its handler by name). Retries lean
# on the outbox: five attempts with exponential backoff, then dead-letter.
WEBHOOK_DELIVER = JobDefinition(
    name="webhooks.delivery.send",
    payload_schema=WebhookDeliveryPayload,
    handler=deliver_webhook,
    retry=RetryPolicy(max_attempts=5, backoff_seconds=10.0),
    queue="webhooks",
    visibility=JobVisibility.INTERNAL,
)


__all__ = [
    "WEBHOOK_DELIVER",
    "WebhookDeliveryError",
    "WebhookDeliveryPayload",
    "WebhookResponse",
    "WebhookSender",
    "active_webhook_sender",
    "deliver_webhook",
    "reset_webhook_sender",
    "set_webhook_sender",
]
