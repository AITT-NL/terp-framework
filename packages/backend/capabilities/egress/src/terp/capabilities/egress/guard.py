"""The egress guard: the declared way out, held at the socket (ADR 0177).

``no_raw_outbound_http`` reads the application's own imports, and :class:`EgressClient`
guards the calls made through it. A vendor SDK installed as a dependency builds its own
HTTP client inside the process. No import in the app names that client, so the build-time
rule cannot see it, and the SDK never goes through the egress client. Until this module,
the SSRF denylist and the host allowlist held for the app's own calls and for nobody
else's.

:func:`install_egress_guard` holds them for every library that reaches the network through
the standard library's ``socket`` module. It registers a Python audit hook (PEP 578) over
exactly these events:

* A name lookup: ``socket.getaddrinfo``, and ``socket.gethostbyname`` (raised by
  ``gethostbyname`` and ``gethostbyname_ex``). A hostname must be declared: a host the
  app's egress policies allow, a host a vendor SDK is declared to reach, or
  infrastructure. An undeclared name is refused before these calls look it up.
  ``localhost`` and IP literals pass here, because they name an address and the address
  rule below holds it. A server binding ``0.0.0.0`` makes the same lookup.
* A connection or a datagram on an ``AF_INET`` or ``AF_INET6`` socket: ``socket.connect``
  (raised by ``connect`` and ``connect_ex``), ``socket.sendto`` and ``socket.sendmsg``.
  An address inside the SSRF denylist (private, loopback, link-local, cloud metadata) is
  refused unless it is declared infrastructure. A peer given by name meets the name rule,
  and is then resolved by the guard: every address it names for the socket's family meets
  the address rule, ``localhost`` included. A peer that is neither a name nor an address
  is refused. Other families (``AF_UNIX``, ``AF_PACKET``, ``AF_NETLINK``) have no IP peer
  and pass.

What it cannot hold is named, here and in ADR 0177:

* **uvloop.** It resolves and connects inside libuv and raises no audit event, so every
  connection on its event loop would pass unseen. :func:`install_egress_guard` refuses to
  install while uvloop is imported, running or set as the event-loop policy, and the hook
  refuses a later ``import uvloop``, with :class:`EgressGuardUnsupportedError`. uvicorn
  picks uvloop whenever it is installed (``uvicorn[standard]``): run it with
  ``--loop asyncio``, and run a worker or scheduler with ``asyncio.run``. Any other event
  loop written in native code is invisible the same way.
* **Native clients** that open their own sockets (libpq, the gRPC C core, librdkafka).
  Those are infrastructure drivers in practice, and the deployment's network policy holds
  them.
* **A connect by name is resolved before its event.** CPython resolves the peer of a
  ``connect`` or ``sendto`` by name before it raises the event, so an undeclared name
  given there reaches DNS before the connect is refused, and the guard's own resolution
  can differ from the one CPython connects to. The common stacks look up first and
  connect by address, and an address is held exactly.
* **Public addresses** pass. The name rule holds public destinations, and a public IP
  literal is not a name.
* **Reverse lookups** (``gethostbyaddr``, ``getnameinfo``) are not held. ``getfqdn()``,
  which ``smtplib`` calls for its greeting, makes one for the machine's own name.
* **How a refusal arrives.** It is :class:`EgressRefusedError`, deliberately not an
  ``OSError``, so a library's connection-error handling does not swallow it. For the same
  reason that handling does not close the socket it opened: ``create_connection`` and
  urllib3 close on ``OSError`` only, so a refused socket is left to the garbage collector
  (a ``ResourceWarning``). Under an async client (httpx on anyio) a refused connect can
  arrive inside an ``ExceptionGroup``.
* **Windows.** The ``socketpair`` fallback every asyncio event loop uses there connects to
  ``127.0.0.1``, so creating an event loop after install is refused unless loopback is
  declared infrastructure. The production target is Linux.
* It holds where the process is steered, not what code running in it may do: such code
  can reach the network without the ``socket`` module at all.

An audit hook cannot be removed. The hook is registered once per process and reads the
installed guard on every event; with none installed it returns at once.
"""

from __future__ import annotations

import asyncio
import ipaddress
import math
import sys
import time
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Lock, local
from typing import Any

from terp.capabilities.egress.errors import EgressRefusedError
from terp.capabilities.egress.policy import EgressPolicy
from terp.capabilities.egress.ssrf import (
    IP_VERSION_BY_FAMILY,
    Resolver,
    as_ip_literal,
    is_denied_address,
    resolve_host,
)

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

#: How long a resolution of the infrastructure names is trusted before a connect to an
#: unrecognised private address may resolve them again. It bounds the DNS that a run of
#: refused connects can cost, and how stale a moved database address can be.
INFRASTRUCTURE_REFRESH_SECONDS = 5.0

#: Passes the name rule without being declared: it names loopback. A lookup of it passes
#: (a bind makes one); a connect or a datagram to it is resolved, and each loopback address
#: meets the address rule like any other.
_ALWAYS_RESOLVABLE = frozenset({"localhost"})

#: The cloud metadata endpoints. A resolved infrastructure name never sanctions one; only
#: an explicit literal or network in ``infrastructure`` can.
_METADATA_ADDRESSES: frozenset[_IPAddress] = frozenset(
    {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
)

#: Event loops written in native code: they resolve and connect without an audit event.
_NATIVE_EVENT_LOOPS = frozenset({"uvloop"})

_LOOKUP_EVENTS = frozenset({"socket.getaddrinfo", "socket.gethostbyname"})
_CONNECTION_EVENTS = frozenset({"socket.connect", "socket.sendto", "socket.sendmsg"})

#: The guard's clock, read through the module so a test moves it for the guard alone.
_monotonic = time.monotonic


class EgressGuardUnsupportedError(RuntimeError):
    """The process runs an event loop the guard cannot see into, so it is not installed.

    Raised by :func:`install_egress_guard`, and by the hook when such a loop is imported
    after it. A guard that installs and then sees nothing would be worse than none: the
    declaration would read as enforced.
    """


def _bare_name(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _normalized(ip: _IPAddress) -> _IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _require_hostname(field: str, name: str) -> None:
    """Refuse a name the resolver could not encode, at declaration rather than at a connect."""
    try:
        name.encode("idna")
    except UnicodeError as exc:
        raise ValueError(f"EgressGuard.{field} entries must be valid hostnames: {name!r}") from exc


def _refusal(reason: str, **context: str) -> EgressRefusedError:
    return EgressRefusedError(
        "The outbound request was not permitted.",
        log_context={"reason": reason, **context, "control": "egress_guard"},
    )


@dataclass(frozen=True)
class EgressGuard:
    """What the process may reach, declared once at the composition root.

    ``hosts`` are the public names outbound traffic may resolve: every host an
    :class:`EgressPolicy` allows, and every host a vendor SDK is documented to call. They
    are names, never addresses and never with a port. ``infrastructure`` is what the
    deployment itself runs on, such as the database, Redis, the mail relay and a telemetry
    collector. Each entry is a hostname, an IP literal or a CIDR network. Infrastructure may
    sit on private addresses; nothing else may.
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
            if ":" in host or as_ip_literal(host) is not None:
                raise ValueError(
                    "EgressGuard.hosts entries are names without a port; an address the "
                    f"process may reach is declared as infrastructure: {host!r}"
                )
            _require_hostname("hosts", host)
        for entry in self.infrastructure:
            if not entry or entry.strip() != entry or "*" in entry:
                raise ValueError(
                    "EgressGuard.infrastructure entries are hostnames, IP literals or CIDR "
                    f"networks: {entry!r}"
                )
            if "/" in entry:
                ipaddress.ip_network(entry, strict=False)
            elif as_ip_literal(entry) is None:
                if ":" in entry:
                    raise ValueError(
                        f"EgressGuard.infrastructure names carry no port: {entry!r}"
                    )
                _require_hostname("infrastructure", entry)

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
        public hosts. An IP literal in any other policy needs no name: a public one passes
        the address rule, and the client refuses a private one.
        """
        public: list[str] = []
        internal: list[str] = []
        for policy in policies:
            for host in map(_bare_name, policy.allowed_hosts):
                if policy.allow_private_addresses:
                    internal.append(host)
                elif as_ip_literal(host) is None:
                    public.append(host)
        public.extend(hosts)
        internal.extend(infrastructure)
        return cls(hosts=tuple(dict.fromkeys(public)), infrastructure=tuple(dict.fromkeys(internal)))


#: Set while the guard's own resolver runs on this thread. Its lookups, and any socket a
#: custom resolver opens, pass straight through rather than re-entering the guard.
_resolving = local()


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
        self._infrastructure_names = tuple(sorted(set(names)))
        self._names = frozenset(guard.hosts) | frozenset(names) | _ALWAYS_RESOLVABLE
        # Resolved once now, so threads that connect together at start-up find the
        # database without each needing a lookup. The window stays open: the first
        # unrecognised private connect resolves again, in case DNS was not ready yet.
        self._infrastructure_addresses = self._resolve_infrastructure()
        self._resolved_at = -math.inf
        self._lock = Lock()

    def check_event(self, event: str, args: tuple[Any, ...]) -> None:
        if event in _LOOKUP_EVENTS:
            host = _host_text(args[0]) if args else None
            if host is not None:
                self.check_lookup(host)
        elif event in _CONNECTION_EVENTS and len(args) > 1:
            self.check_peer(args[0], args[1])

    def check_lookup(self, host: str) -> None:
        """A lookup of a name meets the name rule; a literal is left to the connect."""
        name = _bare_name(host)
        if as_ip_literal(name) is None and name not in self._names:
            raise _refusal("undeclared_host", host=name)

    def check_peer(self, sock: object, address: object) -> None:
        """Hold the peer of a connect or a datagram on an IP socket."""
        # CPython passes the socket. One whose family cannot be read is held as an IP
        # socket: the guard does not wave through what it cannot identify.
        family = getattr(sock, "family", None)
        if family is not None and family not in IP_VERSION_BY_FAMILY:
            return
        # None is a connected socket's sendmsg, which names no peer. Any other non-tuple
        # is refused by CPython itself, before it is sent anywhere.
        if not isinstance(address, tuple):
            return
        host = _host_text(address[0]) if address else None
        if host is None:
            raise _refusal("malformed_peer", peer=repr(address)[:120])
        name = _bare_name(host)
        if (literal := as_ip_literal(name)) is not None:
            self.check_address(ipaddress.ip_address(literal))
            return
        self.check_lookup(name)
        version = IP_VERSION_BY_FAMILY.get(family)
        addresses = [
            ip for ip in self._resolve(name) or () if version is None or ip.version == version
        ]
        if not addresses:
            raise _refusal("unresolvable", host=name)
        for ip in addresses:
            self.check_address(ip)

    def check_address(self, ip: _IPAddress) -> None:
        if not is_denied_address(str(ip)) or self._is_infrastructure(_normalized(ip)):
            return
        raise _refusal("denied_address", address=str(ip))

    def _is_infrastructure(self, ip: _IPAddress) -> bool:
        if any(ip.version == network.version and ip in network for network in self._networks):
            return True
        if ip in self._infrastructure_addresses:
            return True
        if not self._infrastructure_names:
            return False
        self._refresh_infrastructure()
        return ip in self._infrastructure_addresses

    def _refresh_infrastructure(self) -> None:
        """Resolve the infrastructure names again, at most once per window.

        The window is claimed under the lock and the names are resolved outside it, so a
        slow DNS server holds up only the connect that asked. A miss while another thread
        resolves is decided on the addresses already known.
        """
        with self._lock:
            claimed = _monotonic()
            if claimed - self._resolved_at < INFRASTRUCTURE_REFRESH_SECONDS:
                return
            self._resolved_at = claimed
        resolved = self._resolve_infrastructure()
        with self._lock:
            if self._resolved_at == claimed:  # no later refresh has claimed the window
                self._infrastructure_addresses = resolved

    def _resolve_infrastructure(self) -> frozenset[_IPAddress]:
        found = {
            _normalized(ip) for name in self._infrastructure_names for ip in self._resolve(name) or ()
        }
        return frozenset(found - _METADATA_ADDRESSES)

    def _resolve(self, name: str) -> list[_IPAddress] | None:
        """Every address *name* resolves to, or ``None`` when it does not resolve."""
        outer = getattr(_resolving, "active", False)
        _resolving.active = True
        try:
            return [ipaddress.ip_address(address) for address in self._resolver(name)]
        except (OSError, ValueError):  # ValueError includes the UnicodeError of a bad name
            return None
        finally:
            _resolving.active = outer


_installed: _InstalledGuard | None = None
_hook_registered = False
_registration_lock = Lock()


def _host_text(host: object) -> str | None:
    if isinstance(host, bytes | bytearray):
        return host.decode("ascii", "replace")
    return host if isinstance(host, str) else None


def _from_native_loop(obj: object) -> bool:
    return any(cls.__module__.partition(".")[0] in _NATIVE_EVENT_LOOPS for cls in type(obj).__mro__)


def _event_loop_policy() -> object:
    # Policies are deprecated from Python 3.14, but uvloop.install() still sets one.
    get_policy = getattr(asyncio, "get_event_loop_policy", lambda: None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return get_policy()


def _native_loop_in_use() -> str | None:
    imported = sorted(name for name in _NATIVE_EVENT_LOOPS if name in sys.modules)
    if imported:
        return f"{imported[0]} is imported"
    try:
        loop: object = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    for role, obj in (("running event loop", loop), ("event-loop policy", _event_loop_policy())):
        if _from_native_loop(obj):
            return f"the {role} is {type(obj).__module__}.{type(obj).__qualname__}"
    return None


def _unsupported(found: str) -> EgressGuardUnsupportedError:
    return EgressGuardUnsupportedError(
        f"The egress guard cannot hold this process: {found}. uvloop resolves names and "
        "opens connections inside libuv, which raises no Python audit event, so every "
        "connection made on its event loop would pass the guard unseen. Run uvicorn with "
        '--loop asyncio (loop="asyncio" when it is started from code), and run a worker '
        "or scheduler that installs the guard with asyncio.run, not uvloop."
    )


def _audit(event: str, args: tuple[Any, ...]) -> None:
    installed = _installed
    if installed is None:
        return
    if event == "import":
        module = args[0] if args else None
        if isinstance(module, str) and module.partition(".")[0] in _NATIVE_EVENT_LOOPS:
            raise _unsupported(f"{module} is being imported")
    elif event.startswith("socket.") and not getattr(_resolving, "active", False):
        installed.check_event(event, args)


# CPython pauses tracing inside an audit hook unless the hook opts in. Opting in lets a
# tracer (coverage, a debugger) see what the hook does; it changes nothing the hook decides.
_audit.__cantrace__ = True  # type: ignore[attr-defined]


def install_egress_guard(guard: EgressGuard, *, resolver: Resolver = resolve_host) -> None:
    """Hold every socket in this process to *guard*, from now on.

    Install it in the composition root that the web process and the worker both run, so
    that both are held. Installing again replaces the guard in force. Raises
    :class:`EgressGuardUnsupportedError` in a process that runs uvloop.
    """
    global _installed, _hook_registered
    found = _native_loop_in_use()
    if found is not None:
        raise _unsupported(found)
    installed = _InstalledGuard(guard, resolver)
    with _registration_lock:
        if not _hook_registered:
            sys.addaudithook(_audit)
            _hook_registered = True
        _installed = installed


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
    "EgressGuardUnsupportedError",
    "install_egress_guard",
    "installed_egress_guard",
    "uninstall_egress_guard",
]
