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
registration but a private one at delivery — is still blocked). The denylist is a pure,
table-driven predicate (:func:`is_denied_address`) so it is exhaustively unit-tested.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from terp.core import AppError

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# The explicit, greppable denylist of network ranges a webhook target must never resolve
# into — RFC-1918 private space, loopback, link-local (incl. the 169.254.169.254 cloud
# metadata address), carrier-grade NAT, benchmarking, IETF-assignments, and the IPv6
# unique-local / link-local space. The ``is_*`` flags below are a second, version-robust
# catch-all on top of this list.
_DENIED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network / unspecified source
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 private
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (incl. 169.254.169.254 metadata)
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 private
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 private
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
)

# The cloud-metadata address, called out explicitly so the intent is greppable even though
# it is already inside 169.254.0.0/16.
CLOUD_METADATA_ADDRESS = "169.254.169.254"


class WebhookTargetError(AppError):
    """422 — a webhook target URL is not allowed (wrong scheme or a denied address range)."""

    status_code = 422
    code = "webhook_target_invalid"
    default_message = "The webhook target URL is not allowed."


@dataclass(frozen=True)
class PinnedTarget:
    """A webhook target validated down to a specific, confirmed-safe address.

    ``url`` is the original ``https`` URL (used to build the request, so the ``Host`` header
    and path are correct); ``host`` is its hostname (for TLS SNI + certificate verification);
    ``ip`` is the pre-validated address the sender **pins** the TCP connection to, so a
    DNS-rebinding attacker cannot swap in a private address between the safety check and the
    connect (the TOCTOU a validate-then-reconnect-by-hostname flow would leave open).
    """

    url: str
    host: str
    ip: str


def _is_denied_ip(ip: _IPAddress) -> bool:
    """True if *ip* falls in any denied range (the core denylist predicate)."""
    # An IPv4-mapped IPv6 address (e.g. ``::ffff:127.0.0.1``) is a classic bypass — unwrap
    # it and re-check the embedded IPv4 against the same denylist.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        if _is_denied_ip(ip.ipv4_mapped):
            return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True
    return any(
        ip.version == network.version and ip in network for network in _DENIED_NETWORKS
    )


def is_denied_address(address: str) -> bool:
    """Whether the IP literal *address* is in a denied (SSRF) range — the testable denylist."""
    return _is_denied_ip(ipaddress.ip_address(address))


def _as_ip_literal(host: str) -> str | None:
    """Return *host* as a normalized IP string if it is an IP literal, else ``None``."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _resolve_host(host: str) -> list[str]:
    """Resolve *host* to its IP addresses (every A / AAAA record), failing closed.

    A name that does not resolve is rejected rather than attempted, so an enqueued delivery
    can never fall back to an ambiguous or attacker-controlled lookup at send time.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebhookTargetError(
            f"the webhook target host {host!r} could not be resolved"
        ) from exc
    return [info[4][0] for info in infos]


def _resolve_and_validate(
    url: str, resolve: Callable[[str], list[str]] | None
) -> tuple[str, list[str]]:
    """Parse *url*, require ``https`` + a host, resolve it, and validate every address.

    Returns ``(host, addresses)`` with every resolved address confirmed outside the denied
    ranges, or raises :class:`WebhookTargetError`. An IP-literal host skips DNS. *resolve* is
    an injectable name resolver (defaults to :func:`socket.getaddrinfo`) so the hostname path
    is testable without real DNS.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WebhookTargetError("the webhook target URL must use https")
    host = parts.hostname
    if not host:
        raise WebhookTargetError("the webhook target URL must include a host")
    literal = _as_ip_literal(host)
    if literal is not None:
        addresses = [literal]
    else:
        resolver = resolve if resolve is not None else _resolve_host
        addresses = resolver(host)
    if not addresses:
        raise WebhookTargetError(f"the webhook target host {host!r} did not resolve")
    for address in addresses:
        if _is_denied_ip(ipaddress.ip_address(address)):
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
