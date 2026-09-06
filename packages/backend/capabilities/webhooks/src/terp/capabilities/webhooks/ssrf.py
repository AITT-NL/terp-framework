"""SSRF defense for outbound webhook targets — this capability's top OWASP risk.

A webhook makes the **server** issue an HTTP request to a caller-supplied URL, so an
unvalidated target is a Server-Side Request Forgery primitive: a caller could point it at
``http://169.254.169.254/`` (cloud metadata), ``http://127.0.0.1`` / an RFC-1918 address
(internal services), or a link-local host and have the server reach it.
:func:`validate_webhook_target` fails closed — it requires ``https``, resolves the host,
and rejects the target if **any** resolved address falls in a private / loopback /
link-local / metadata / reserved range.

It is enforced **twice** (defense in depth): at subscription create / update time (a bad
URL is rejected at the API boundary, 422) **and** again inside the delivery job immediately
before the request (so a DNS-rebinding attack — a name that resolved to a public address at
registration but a private one at delivery — is still blocked).

**The denylist itself now lives in the egress capability** (``terp.capabilities.egress``),
which is the platform's declared way out of the process. It moved there rather than being
copied: two lists of forbidden network ranges drift, and the one that drifts is the one
nobody is looking at. What stays here is what is genuinely webhook-shaped — the 422 at the
API boundary, and the messages a subscriber sees when their URL is rejected.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from terp.capabilities.egress import (
    CLOUD_METADATA_ADDRESS,
    PinnedTarget,
    as_ip_literal,
    is_denied_address,
    resolve_host,
)
from terp.core import AppError


class WebhookTargetError(AppError):
    """422 — a webhook target URL is not allowed (wrong scheme or a denied address range)."""

    status_code = 422
    code = "webhook_target_invalid"
    default_message = "The webhook target URL is not allowed."


def _resolve(host: str) -> list[str]:
    """Resolve *host*, turning an unresolvable name into the boundary's own 422.

    Fails closed rather than attempting the delivery: a name that does not resolve now
    must not fall back to an ambiguous lookup at send time.
    """
    try:
        return resolve_host(host)
    except OSError as exc:
        raise WebhookTargetError(
            f"the webhook target host {host!r} could not be resolved"
        ) from exc


def _resolve_and_validate(
    url: str, resolve: Callable[[str], list[str]] | None
) -> tuple[str, list[str]]:
    """Parse *url*, require ``https`` + a host, resolve it, and validate every address.

    Returns ``(host, addresses)`` with every resolved address confirmed outside the denied
    ranges, or raises :class:`WebhookTargetError`. An IP-literal host skips DNS. *resolve* is
    an injectable name resolver (defaults to the egress capability's resolver) so the
    hostname path is testable without real DNS.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WebhookTargetError("the webhook target URL must use https")
    host = parts.hostname
    if not host:
        raise WebhookTargetError("the webhook target URL must include a host")
    literal = as_ip_literal(host)
    if literal is not None:
        addresses = [literal]
    else:
        resolver = resolve if resolve is not None else _resolve
        addresses = resolver(host)
    if not addresses:
        raise WebhookTargetError(f"the webhook target host {host!r} did not resolve")
    for address in addresses:
        if is_denied_address(address):
            raise WebhookTargetError(
                f"the webhook target resolves to a disallowed address ({address})"
            )
    return host, addresses


def validate_webhook_target(
    url: str, *, resolve: Callable[[str], list[str]] | None = None
) -> None:
    """Validate *url* as a safe outbound webhook target (raise :class:`WebhookTargetError`).

    The boundary check (create / update): fails closed unless the URL uses ``https``, has a
    host, and **every** address it resolves to is outside the denied ranges.
    """
    _resolve_and_validate(url, resolve)


def resolve_pinned_target(
    url: str, *, resolve: Callable[[str], list[str]] | None = None
) -> PinnedTarget:
    """Validate *url* and return a :class:`PinnedTarget` bound to a confirmed-safe address.

    The delivery-time check: it resolves + validates **once** and returns the exact address
    the sender must connect to, so the connection cannot be re-resolved to a different
    (malicious) IP between the check and the connect — closing the DNS-rebinding TOCTOU that a
    validate-then-reconnect-by-hostname flow leaves open. When the host resolves to several
    safe addresses, the first is pinned (all were validated).
    """
    host, addresses = _resolve_and_validate(url, resolve)
    return PinnedTarget(url=url, host=host, ip=addresses[0])


__all__ = [
    "CLOUD_METADATA_ADDRESS",
    "PinnedTarget",
    "WebhookTargetError",
    "is_denied_address",
    "resolve_pinned_target",
    "validate_webhook_target",
]
