"""The egress guard: the declared way out, held at the socket (ADR 0177).

``no_raw_outbound_http`` reads the application's own imports, and :class:`EgressClient`
guards the calls made through it. A vendor SDK installed as a dependency builds its own
HTTP client inside the process. No import in the app names that client, so the build-time
rule cannot see it, and the SDK never goes through the egress client. Until this module,
the SSRF denylist and the host allowlist held for the app's own calls and for nobody
else's.

:func:`install_egress_guard` holds them for every caller. It registers a Python audit hook
(PEP 578) that sees two kinds of event, raised by any library in the process:

* ``socket.getaddrinfo``, a name lookup. A hostname must be declared: a host the app's
  egress policies allow, a host a vendor SDK is declared to reach, or infrastructure. An
  undeclared name is refused before it resolves, so an undeclared destination is never
  contacted and a steerable URL cannot reach an internal name. ``localhost`` and IP
  literals pass here: they name an address, and the address rule below holds them.
* ``socket.connect``, ``socket.sendto`` and ``socket.sendmsg``, a connection or a
  datagram. An address inside the SSRF denylist (private, loopback, link-local, cloud
  metadata) is refused unless it is declared infrastructure. A literal
  ``169.254.169.254``, a private address, and a declared public name that rebinds to a
  private address are all refused at the connect. A host passed here by name is held to
  the name rule.

The guard cannot see a client in native code that opens its own sockets (libpq, the gRPC
C core, librdkafka), because such a client raises no Python audit event. In practice those
are infrastructure drivers, and the deployment's network policy is their control.

An audit hook cannot be removed. The hook is registered once per process and reads the
installed guard on every event; with none installed it returns at once.
"""

from __future__ import annotations

import ipaddress
import math
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from threading import Lock
from typing import Any

from terp.capabilities.egress.errors import EgressRefusedError
from terp.capabilities.egress.policy import EgressPolicy
from terp.capabilities.egress.ssrf import Resolver, as_ip_literal, is_denied_address, resolve_host

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

#: How long a resolution of the infrastructure names is trusted before a connect to an
#: unrecognised private address may resolve them again. It bounds the DNS that a run of
#: refused connects can cost, and how stale a moved database address can be.
INFRASTRUCTURE_REFRESH_SECONDS = 5.0

#: Looked up, never refused: resolving it reaches no network, and the loopback address it
#: yields is held to the address rule at the connect like any other.
_ALWAYS_RESOLVABLE = frozenset({"localhost"})

_CONNECTION_EVENTS = frozenset({"socket.connect", "socket.sendto", "socket.sendmsg"})


def _bare_name(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _normalized(ip: _IPAddress) -> _IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


@dataclass(frozen=True)
class EgressGuard:
    """What the process may reach, declared once at the composition root.

    ``hosts`` are the public names outbound traffic may resolve: every host an
    :class:`EgressPolicy` allows, and every host a vendor SDK is documented to call.
    ``infrastructure`` is what the deployment itself runs on, such as the database, Redis,
    the mail relay and a telemetry collector. Each entry is a hostname, an IP literal or a
    CIDR network. Infrastructure may sit on private addresses; nothing else may.
    """

    hosts: tuple[str, ...] = ()
    infrastructure: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for host in self.hosts:
            if not host or _bare_name(host) != host or "*" in host or "/" in host:
                raise ValueError(
                    "EgressGuard.hosts entries are exact, bare lowercase hostnames: "
                    f"{host!r}"
                )
        for entry in self.infrastructure:
            if not entry or entry.strip() != entry or "*" in entry:
                raise ValueError(
                    "EgressGuard.infrastructure entries are hostnames, IP literals or CIDR "
                    f"networks: {entry!r}"
                )
            if "/" in entry:
                ipaddress.ip_network(entry, strict=False)

    @classmethod
    def for_policies(
        cls,
        *policies: EgressPolicy,
        hosts: Iterable[str] = (),
        infrastructure: Iterable[str] = (),
    ) -> EgressGuard:
        """The guard the declared policies imply, plus what reaches out without them.

        A policy that opens the denylist (``allow_private_addresses``) declares its hosts
        as sanctioned internal targets, so they join the infrastructure rather than the
        public hosts.
        """
        public: list[str] = []
        internal: list[str] = []
        for policy in policies:
            (internal if policy.allow_private_addresses else public).extend(policy.allowed_hosts)
        public.extend(hosts)
        internal.extend(infrastructure)
        return cls(hosts=tuple(dict.fromkeys(public)), infrastructure=tuple(dict.fromkeys(internal)))


class _InstalledGuard:
    """The runtime half of one :class:`EgressGuard`: its lookups and its refusals."""

    def __init__(self, guard: EgressGuard, resolver: Resolver) -> None:
        self.guard = guard
        self._resolver = resolver
        networks: list[_Network] = []
        names: list[str] = []
        for entry in guard.infrastructure:
            if "/" in entry:
                networks.append(ipaddress.ip_network(entry, strict=False))
            elif (literal := as_ip_literal(entry)) is not None:
                networks.append(ipaddress.ip_network(literal))
            else:
                names.append(_bare_name(entry))
        self._networks = tuple(networks)
        self._infrastructure_names = frozenset(names)
        self._names = frozenset(guard.hosts) | self._infrastructure_names | _ALWAYS_RESOLVABLE
        self._infrastructure_addresses: frozenset[_IPAddress] = frozenset()
        self._resolved_at = -math.inf
        self._lock = Lock()

    def check_host(self, host: str) -> None:
        """Hold a host to the name rule, or an IP literal to the address rule."""
        name = _bare_name(host)
        literal = as_ip_literal(name)
        if literal is not None:
            self.check_address(literal)
        elif name not in self._names:
            raise EgressRefusedError(
                "The outbound request was not permitted.",
                log_context={"reason": "undeclared_host", "host": name, "control": "egress_guard"},
            )

    def check_lookup(self, host: str) -> None:
        """A lookup names a destination only when it names a host; a literal is checked at the connect."""
        if as_ip_literal(_bare_name(host)) is None:
            self.check_host(host)

    def check_address(self, address: str) -> None:
        if not is_denied_address(address):
            return
        if self._is_infrastructure(_normalized(ipaddress.ip_address(address))):
            return
        raise EgressRefusedError(
            "The outbound request was not permitted.",
            log_context={"reason": "denied_address", "address": address, "control": "egress_guard"},
        )

    def _is_infrastructure(self, ip: _IPAddress) -> bool:
        if any(ip.version == network.version and ip in network for network in self._networks):
            return True
        if ip in self._infrastructure_addresses:
            return True
        if not self._infrastructure_names:
            return False
        with self._lock:
            now = time.monotonic()
            if now - self._resolved_at >= INFRASTRUCTURE_REFRESH_SECONDS:
                self._resolved_at = now
                self._infrastructure_addresses = frozenset(self._resolve_infrastructure())
            return ip in self._infrastructure_addresses

    def _resolve_infrastructure(self) -> Iterator[_IPAddress]:
        # The resolver's own lookups re-enter the hook as getaddrinfo events, and pass:
        # every name resolved here is declared infrastructure.
        for name in sorted(self._infrastructure_names):
            try:
                addresses = self._resolver(name)
            except OSError:
                continue
            yield from (_normalized(ipaddress.ip_address(address)) for address in addresses)


_installed: _InstalledGuard | None = None
_hook_registered = False
_registration_lock = Lock()


def _host_text(host: object) -> str | None:
    if isinstance(host, bytes):
        return host.decode("ascii", "replace")
    return host if isinstance(host, str) else None


def _audit(event: str, args: tuple[Any, ...]) -> None:
    installed = _installed
    if installed is None or not event.startswith("socket."):
        return
    if event == "socket.getaddrinfo":
        host = _host_text(args[0])
        if host is not None:
            installed.check_lookup(host)
    elif event in _CONNECTION_EVENTS:
        address = args[1] if len(args) > 1 else None
        # A tuple names a network peer; a path (AF_UNIX) or None (a connected socket's
        # sendmsg) names none.
        if isinstance(address, tuple) and address:
            host = _host_text(address[0])
            if host is not None:
                installed.check_host(host)


# CPython pauses tracing inside an audit hook unless the hook opts in. Opting in lets a
# tracer (coverage, a debugger) see what the hook does; it changes nothing the hook decides.
_audit.__cantrace__ = True  # type: ignore[attr-defined]


def install_egress_guard(guard: EgressGuard, *, resolver: Resolver = resolve_host) -> None:
    """Hold every socket in this process to *guard*, from now on.

    Install it in the composition root that the web process and the worker both run, so
    that both are held. Installing again replaces the guard in force.
    """
    global _installed, _hook_registered
    with _registration_lock:
        if not _hook_registered:
            sys.addaudithook(_audit)
            _hook_registered = True
        _installed = _InstalledGuard(guard, resolver)


def uninstall_egress_guard() -> None:
    """Make the hook inert again. It cannot be removed; it stops refusing anything."""
    global _installed
    with _registration_lock:
        _installed = None


def installed_egress_guard() -> EgressGuard | None:
    """The guard in force, or ``None``."""
    installed = _installed
    return None if installed is None else installed.guard


__all__ = [
    "INFRASTRUCTURE_REFRESH_SECONDS",
    "EgressGuard",
    "install_egress_guard",
    "installed_egress_guard",
    "uninstall_egress_guard",
]
