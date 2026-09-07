"""The address denylist every outbound call is held to — SSRF, one table, one predicate.

An application that reaches the network on its own behalf is a Server-Side Request
Forgery primitive the moment any part of the destination is influenced from outside:
a caller who can steer a URL can point the *server* at ``http://169.254.169.254/``
(cloud metadata), at an RFC-1918 address (internal services), or at loopback.

This module is the part of that defence that is not specific to any one caller: the
table of ranges an outbound connection must never land in, the predicate over it, and
the resolve-then-pin step that closes the DNS-rebinding window between the check and
the connect. It is deliberately pure and table-driven so it can be exhaustively
unit-tested, and it lives in the egress capability so that every outbound path in the
platform is held to the *same* list rather than to a copy of it.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# The explicit, greppable denylist of network ranges an outbound target must never
# resolve into — RFC-1918 private space, loopback, link-local (incl. the
# 169.254.169.254 cloud metadata address), carrier-grade NAT, benchmarking, IETF
# assignments, and the IPv6 unique-local / link-local space. The ``is_*`` flags in
# :func:`_is_denied_ip` are a second, version-robust catch-all on top of this list.
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

#: The cloud-metadata address, called out explicitly so the intent is greppable even
#: though it already falls inside ``169.254.0.0/16``.
CLOUD_METADATA_ADDRESS = "169.254.169.254"


@dataclass(frozen=True)
class PinnedTarget:
    """A target validated down to one specific, confirmed-safe address.

    ``url`` is the original URL (used to build the request, so the ``Host`` header and
    path are correct); ``host`` is its hostname (for TLS SNI and certificate
    verification); ``ip`` is the pre-validated address the caller **pins** the TCP
    connection to, so a DNS-rebinding attacker cannot swap in a private address between
    the safety check and the connect — the TOCTOU a validate-then-reconnect-by-hostname
    flow leaves open.
    """

    url: str
    host: str
    ip: str


def _is_denied_ip(ip: _IPAddress) -> bool:
    """True if *ip* falls in any denied range (the core denylist predicate)."""
    # An IPv4-mapped IPv6 address (e.g. ``::ffff:127.0.0.1``) is a classic bypass —
    # unwrap it and re-check the embedded IPv4 against the same denylist.
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
    return any(ip.version == network.version and ip in network for network in _DENIED_NETWORKS)


def is_denied_address(address: str) -> bool:
    """Whether the IP literal *address* is in a denied (SSRF) range — the testable denylist."""
    return _is_denied_ip(ipaddress.ip_address(address))


def as_ip_literal(host: str) -> str | None:
    """Return *host* as a normalized IP string if it is an IP literal, else ``None``."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def resolve_host(host: str) -> list[str]:
    """Every address *host* resolves to (all A / AAAA records).

    Raises :class:`OSError` when the name does not resolve; every caller treats that as
    a refusal rather than an attempt, so an unresolvable name can never fall back to an
    ambiguous or attacker-controlled lookup at send time.
    """
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


#: An injectable name resolver, so the hostname path is testable without real DNS.
Resolver = Callable[[str], list[str]]


__all__ = [
    "CLOUD_METADATA_ADDRESS",
    "PinnedTarget",
    "Resolver",
    "as_ip_literal",
    "is_denied_address",
    "resolve_host",
]
