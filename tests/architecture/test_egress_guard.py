"""The egress guard: the declaration held at the socket, for every library (ADR 0177).

The egress client guards the calls made through it, and a vendor SDK makes its own. These
tests hold the process-wide half. A lookup of an undeclared name and a connection into a
denied range are refused wherever they come from: a real ``socket.getaddrinfo``, a real
``socket.connect``, a real HTTP client, or the audit events a library raises on the way to
one.

Every refusal below happens before the network is touched. The audit hook runs ahead of
the lookup or the connect it audits, which is the property the guard rests on, so the
real-socket cases need no network at all. Where a failing guard would let a real client
try, the client has a short timeout, so a regression fails instead of hanging.
"""

from __future__ import annotations

import asyncio
import gc
import http.client
import ipaddress
import socket
import sys
import threading
import types
import urllib.request
import warnings
from collections.abc import Iterator

import pytest

from terp.capabilities import egress
from terp.capabilities.egress import (
    CLOUD_METADATA_ADDRESS,
    INFRASTRUCTURE_REFRESH_SECONDS,
    EgressAttempt,
    EgressClient,
    EgressGuard,
    EgressGuardUnsupportedError,
    EgressPolicy,
    EgressRefusedError,
    install_egress_guard,
    installed_egress_guard,
    uninstall_egress_guard,
)
from terp.capabilities.egress import guard as guard_module

_VENDOR = "api.vendor.example"

#: A family whose peers are not IP addresses (AF_UNIX on every platform that has one).
_NOT_IP = getattr(socket, "AF_UNIX", 1)


class _Sock:
    """Just enough of a socket for the hook to read its family."""

    def __init__(self, family: int) -> None:
        self.family = family


def _no_dns(name: str) -> list[str]:
    raise OSError(f"{name}: no lookups in this test")


@pytest.fixture(autouse=True)
def _inert_after_each_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Whatever an earlier test imported, these tests decide for themselves whether uvloop
    # is in the process.
    for name in [name for name in sys.modules if name.partition(".")[0] == "uvloop"]:
        monkeypatch.delitem(sys.modules, name)
    uninstall_egress_guard()
    yield
    uninstall_egress_guard()


def _reason(excinfo: pytest.ExceptionInfo[EgressRefusedError]) -> str:
    return excinfo.value.log_context["reason"]


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #
def test_an_undeclared_name_is_refused_before_it_resolves() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError) as refused:
        socket.getaddrinfo("internal-admin.corp.example", 443)
    assert _reason(refused) == "undeclared_host"
    assert refused.value.log_context["control"] == "egress_guard"


def test_the_older_lookups_are_held_to_the_same_rule() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError):
        socket.gethostbyname("internal-admin.corp.example")
    with pytest.raises(EgressRefusedError):
        socket.gethostbyname_ex("internal-admin.corp.example")
    sys.audit("socket.gethostbyname", _VENDOR)
    sys.audit("socket.gethostbyname", "10.0.0.1")  # a literal is held at the connect
    assert socket.gethostbyname("localhost")


def test_declared_names_resolve_as_written_and_localhost_always_does() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,), infrastructure=("db",)), resolver=_no_dns)
    sys.audit("socket.getaddrinfo", _VENDOR, 443, 0, 0, 0)
    sys.audit("socket.getaddrinfo", "API.Vendor.Example.", 443, 0, 0, 0)
    sys.audit("socket.getaddrinfo", b"db", 5432, 0, 0, 0)
    assert socket.getaddrinfo("localhost", 80)


def test_a_literal_or_an_empty_lookup_is_left_to_the_connect() -> None:
    # A server binding 0.0.0.0 looks it up too, and the event does not say it is passive.
    install_egress_guard(EgressGuard())
    assert socket.getaddrinfo("0.0.0.0", 8000)  # noqa: S104 - the lookup a bind makes, not a bind
    assert socket.getaddrinfo(None, 8000)
    sys.audit("socket.getaddrinfo", CLOUD_METADATA_ADDRESS, 80, 0, 0, 0)
    sys.audit("socket.getaddrinfo")


# --------------------------------------------------------------------------- #
# connections by address
# --------------------------------------------------------------------------- #
def test_a_real_connect_into_the_metadata_range_is_refused_before_it_is_made() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(EgressRefusedError) as refused:
            sock.connect((CLOUD_METADATA_ADDRESS, 80))
    assert _reason(refused) == "denied_address"
    assert refused.value.log_context["address"] == CLOUD_METADATA_ADDRESS


def test_real_http_clients_are_refused_before_they_connect() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    url = f"http://{CLOUD_METADATA_ADDRESS}/latest/meta-data/"
    with warnings.catch_warnings():
        # The refused socket is left to the collector: a library closes on OSError only.
        warnings.simplefilter("ignore", ResourceWarning)
        connection = http.client.HTTPConnection(CLOUD_METADATA_ADDRESS, 80, timeout=1)
        with pytest.raises(EgressRefusedError) as refused:
            connection.request("GET", "/latest/meta-data/")
        assert refused.value.log_context["address"] == CLOUD_METADATA_ADDRESS
        with pytest.raises(EgressRefusedError):
            urllib.request.urlopen(url, timeout=1)  # noqa: S310 - the refusal is the point
        del refused
        gc.collect()


def test_the_egress_client_reports_a_guard_refusal_as_a_refusal() -> None:
    attempts: list[EgressAttempt] = []
    client = EgressClient(
        EgressPolicy(
            allowed_hosts=("ledger.internal",),
            allow_private_addresses=True,
            allowed_schemes=("http",),
            timeout_seconds=1,
        ),
        resolve=lambda _host: ["10.255.0.9"],
        observer=attempts.append,
    )
    install_egress_guard(EgressGuard())  # the ledger's address is not declared infrastructure
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        with pytest.raises(EgressRefusedError) as refused:
            client.get("http://ledger.internal/")
        assert refused.value.log_context["control"] == "egress_guard"
        del refused
        gc.collect()
    assert [(attempt.host, attempt.refused) for attempt in attempts] == [("ledger.internal", True)]


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.18.0.3",
        "192.168.1.1",
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "fe80::1",
        "fec0::1",
    ],
)
def test_every_denied_range_is_refused_at_the_connect(address: str) -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, (address, 443))


def test_a_public_address_connects() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    sys.audit("socket.connect", None, ("93.184.216.34", 443))
    sys.audit("socket.connect", _Sock(socket.AF_INET6), ("2606:2800:220:1::", 443, 0, 0))


# --------------------------------------------------------------------------- #
# connections by name: the name rule, then every address it resolves to
# --------------------------------------------------------------------------- #
def test_a_peer_given_by_name_is_resolved_and_every_address_held() -> None:
    answers = {
        _VENDOR: ["93.184.216.34", "2606:2800:220:1::"],
        "rebound.vendor.example": ["93.184.216.34", "10.0.0.7"],
        "dual.vendor.example": ["::1", "93.184.216.34"],
        "empty.vendor.example": [],
    }
    lookups: list[str] = []

    def resolver(name: str) -> list[str]:
        lookups.append(name)
        if name == "idn.vendor.example":
            raise UnicodeError("label empty or too long")
        if name not in answers:
            raise OSError("no such host")
        return answers[name]

    declared = (*answers, "idn.vendor.example", "lost.vendor.example")
    install_egress_guard(EgressGuard(hosts=declared), resolver=resolver)

    with pytest.raises(EgressRefusedError) as refused:  # the name rule first, without a lookup
        sys.audit("socket.connect", None, ("internal.service", 80))
    assert _reason(refused) == "undeclared_host"
    assert lookups == []

    sys.audit("socket.connect", None, (_VENDOR, 443))
    sys.audit("socket.sendto", None, (_VENDOR.encode(), 443))
    with pytest.raises(EgressRefusedError) as refused:  # one private answer refuses the name
        sys.audit("socket.connect", None, ("rebound.vendor.example", 443))
    assert refused.value.log_context["address"] == "10.0.0.7"

    # The socket's family decides which answers it can connect to.
    sys.audit("socket.connect", _Sock(socket.AF_INET), ("dual.vendor.example", 443))
    with pytest.raises(EgressRefusedError) as refused:
        sys.audit("socket.connect", _Sock(socket.AF_INET6), ("dual.vendor.example", 443, 0, 0))
    assert refused.value.log_context["address"] == "::1"

    for name in ("lost.vendor.example", "idn.vendor.example", "empty.vendor.example"):
        with pytest.raises(EgressRefusedError) as refused:
            sys.audit("socket.connect", None, (name, 443))
        assert _reason(refused) == "unresolvable"


def test_localhost_by_name_is_resolved_and_held_at_the_connect() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        install_egress_guard(EgressGuard())
        assert socket.getaddrinfo("localhost", port)  # the lookup a bind makes still passes
        with socket.socket() as client:
            client.settimeout(1)
            with pytest.raises(EgressRefusedError) as refused:
                client.connect(("localhost", port))
        assert refused.value.log_context["address"] == "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
            with pytest.raises(EgressRefusedError):
                datagram.sendto(b"log record", ("localhost", port))

        install_egress_guard(EgressGuard(infrastructure=("127.0.0.1",)))
        with socket.socket() as client:
            client.settimeout(1)
            client.connect(("localhost", port))  # loopback declared: the IPv4 answer passes


def test_a_peer_that_is_neither_a_name_nor_an_address_is_refused() -> None:
    install_egress_guard(EgressGuard())
    with socket.socket() as sock:
        sock.settimeout(1)
        with pytest.raises(EgressRefusedError) as refused:
            sock.connect((bytearray(b"127.0.0.1"), 9))
    assert refused.value.log_context["address"] == "127.0.0.1"
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, (b"10.0.0.1", 80))
    with pytest.raises(EgressRefusedError) as refused:
        sys.audit("socket.connect", _Sock(socket.AF_INET), (2130706433, 80))
    assert _reason(refused) == "malformed_peer"
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.sendto", _Sock(socket.AF_INET6), ())


def test_datagrams_are_held_and_local_or_peerless_sockets_pass() -> None:
    install_egress_guard(EgressGuard())
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.sendto", None, (CLOUD_METADATA_ADDRESS, 53))
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.sendmsg", None, ("10.0.0.1", 53))
    sys.audit("socket.sendmsg", None, None)  # a connected socket names no peer
    sys.audit("socket.connect", None, "/run/postgresql/.s.PGSQL.5432")  # AF_UNIX
    sys.audit("socket.sendto", _Sock(_NOT_IP), ("lo", 0))  # AF_PACKET-shaped
    sys.audit("socket.sendto", _Sock(_NOT_IP), (0, 0))  # AF_NETLINK-shaped
    sys.audit("socket.connect", None)
    sys.audit("socket.bind", None, ("0.0.0.0", 8000))  # noqa: S104 - not a way out
    sys.audit("open", "/etc/hosts", "r", 0)


# --------------------------------------------------------------------------- #
# infrastructure
# --------------------------------------------------------------------------- #
def test_declared_infrastructure_may_sit_on_private_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups: list[str] = []
    answers = {"db": ["172.18.0.3"], "redis": ["::ffff:172.18.0.4"]}

    def resolver(name: str) -> list[str]:
        lookups.append(name)
        if name not in answers:
            raise OSError("no such host")
        return answers[name]

    clock = [100.0]
    monkeypatch.setattr(guard_module, "_monotonic", lambda: clock[0])
    install_egress_guard(
        EgressGuard(infrastructure=("db", "redis", "gone", "10.1.0.0/16", "192.168.5.5")),
        resolver=resolver,
    )
    assert sorted(lookups) == ["db", "gone", "redis"]  # resolved once, at install
    # Networks and literals need no lookup; resolved names (a mapped answer unwrapped) neither.
    for address in ("10.1.2.3", "192.168.5.5", "172.18.0.3", "172.18.0.4"):
        sys.audit("socket.connect", None, (address, 5432))
    assert len(lookups) == 3

    answers["db"] = ["172.18.0.9"]  # the database moved; the first miss looks again
    sys.audit("socket.connect", None, ("172.18.0.9", 5432))
    assert len(lookups) == 6

    with pytest.raises(EgressRefusedError):  # a neighbour on the same network is not infrastructure
        sys.audit("socket.connect", None, ("172.18.0.10", 80))
    assert len(lookups) == 6  # inside the window, a miss does not look again

    clock[0] += INFRASTRUCTURE_REFRESH_SECONDS
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, ("172.18.0.10", 80))
    assert len(lookups) == 9  # past it, one more resolution, then the same answer


def test_a_resolved_name_never_sanctions_the_metadata_endpoint() -> None:
    answers = {"metadata.internal": [CLOUD_METADATA_ADDRESS, "fd00:ec2::254", "10.0.0.8"]}
    install_egress_guard(EgressGuard(infrastructure=("metadata.internal",)), resolver=answers.__getitem__)
    sys.audit("socket.connect", None, ("10.0.0.8", 80))
    for address in (CLOUD_METADATA_ADDRESS, "fd00:ec2::254", f"::ffff:{CLOUD_METADATA_ADDRESS}"):
        with pytest.raises(EgressRefusedError):
            sys.audit("socket.connect", None, (address, 80))

    install_egress_guard(EgressGuard(infrastructure=(CLOUD_METADATA_ADDRESS,)))  # only explicitly
    sys.audit("socket.connect", None, (CLOUD_METADATA_ADDRESS, 80))


def test_a_resolver_that_raises_socket_events_of_its_own_does_not_deadlock() -> None:
    answers = iter([["10.0.0.3"], ["10.0.0.4"]])

    def resolver(name: str) -> list[str]:
        # A resolver that asks a private DNS server raises socket events itself. They pass
        # straight through instead of re-entering the guard that is resolving.
        sys.audit("socket.sendto", None, ("10.0.0.53", 53))
        sys.audit("socket.getaddrinfo", "dns.internal", 53, 0, 0, 0)
        return next(answers)

    install_egress_guard(EgressGuard(infrastructure=("db",)), resolver=resolver)
    outcome: list[object] = []

    def connect() -> None:
        try:
            sys.audit("socket.connect", None, ("10.0.0.4", 5432))  # a miss: resolved again
            outcome.append("connected")
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            outcome.append(exc)

    worker = threading.Thread(target=connect, daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive(), "the guard deadlocked on its own resolver"
    assert outcome == ["connected"]
    with pytest.raises(EgressRefusedError):  # outside the resolver, the same event is held
        sys.audit("socket.sendto", None, ("10.0.0.53", 53))


def test_one_resolution_per_window_and_the_newest_answer_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(guard_module, "_monotonic", lambda: clock[0])
    # At install, then the refresh a miss starts, then a newer one that starts inside it.
    answers = {1: ["172.18.0.3"], 2: ["172.18.0.4"], 3: ["172.18.0.5"]}
    calls: list[int] = []

    def resolver(name: str) -> list[str]:
        calls.append(1)
        call = len(calls)
        if call == 2:  # the refresh after install, still running ...
            installed = guard_module._installed
            assert installed is not None
            # ... a miss on another connect is decided on what is known, not resolved again,
            with pytest.raises(EgressRefusedError):
                installed.check_address(ipaddress.ip_address("172.18.0.9"))
            assert len(calls) == 2
            # ... and a newer window claimed meanwhile is not overwritten by this answer.
            clock[0] += INFRASTRUCTURE_REFRESH_SECONDS
            with pytest.raises(EgressRefusedError):
                installed.check_address(ipaddress.ip_address("172.18.0.9"))
            assert len(calls) == 3
        return answers[call]

    install_egress_guard(EgressGuard(infrastructure=("db",)), resolver=resolver)
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, ("172.18.0.8", 5432))
    assert len(calls) == 3
    sys.audit("socket.connect", None, ("172.18.0.5", 5432))
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, ("172.18.0.4", 5432))


# --------------------------------------------------------------------------- #
# event loops the guard cannot see into
# --------------------------------------------------------------------------- #
def test_the_guard_will_not_install_in_a_process_that_imported_uvloop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "uvloop", types.ModuleType("uvloop"))
    with pytest.raises(EgressGuardUnsupportedError, match="--loop asyncio") as refused:
        install_egress_guard(EgressGuard())
    assert "uvloop is imported" in str(refused.value)
    assert installed_egress_guard() is None


def test_the_guard_will_not_install_inside_a_uvloop_event_loop() -> None:
    loop_class = type("Loop", (asyncio.SelectorEventLoop,), {"__module__": "uvloop"})

    async def install() -> BaseException | None:
        try:
            install_egress_guard(EgressGuard())
        except EgressGuardUnsupportedError as exc:
            return exc
        return None

    refused = asyncio.run(install(), loop_factory=loop_class)
    assert isinstance(refused, EgressGuardUnsupportedError)
    assert "the running event loop is uvloop.Loop" in str(refused)
    assert asyncio.run(install()) is None  # the standard library's loop is held


def test_the_guard_will_not_install_under_a_uvloop_policy() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # policies are deprecated in 3.14
        base = asyncio.DefaultEventLoopPolicy
        asyncio.set_event_loop_policy(type("EventLoopPolicy", (base,), {"__module__": "uvloop"})())
    try:
        with pytest.raises(EgressGuardUnsupportedError, match="event-loop policy is uvloop"):
            install_egress_guard(EgressGuard())
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(None)


def test_importing_uvloop_after_install_is_refused() -> None:
    install_egress_guard(EgressGuard())
    # The statement uvicorn's loop setup runs; refused whether or not uvloop is installed.
    with pytest.raises(EgressGuardUnsupportedError, match="uvloop is being imported"):
        import uvloop  # noqa: F401, PLC0415
    assert "uvloop" not in sys.modules
    with pytest.raises(EgressGuardUnsupportedError):
        sys.audit("import", "uvloop.loop", None, None, None, None)
    sys.audit("import", "uvloopish", None, None, None, None)
    sys.audit("import", "json", None, None, None, None)

    uninstall_egress_guard()
    sys.audit("import", "uvloop", None, None, None, None)


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
def test_the_guard_a_policy_implies_keeps_internal_targets_internal() -> None:
    public = EgressPolicy(allowed_hosts=("api.rates.example.", _VENDOR, "93.184.216.34"))
    internal = EgressPolicy(
        allowed_hosts=("ledger.internal.", "10.0.0.5"), allow_private_addresses=True
    )
    guard = EgressGuard.for_policies(
        public, internal, hosts=(_VENDOR, "sdk.vendor.example"), infrastructure=("db",)
    )
    assert guard.hosts == ("api.rates.example", _VENDOR, "sdk.vendor.example")
    assert guard.infrastructure == ("ledger.internal", "10.0.0.5", "db")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hosts": ("API.vendor.example",)},
        {"hosts": ("*.vendor.example",)},
        {"hosts": ("vendor.example.",)},
        {"hosts": ("10.0.0.0/8",)},
        {"hosts": ("",)},
        {"hosts": ("1.2.3.4",)},  # an address is infrastructure, not a host
        {"hosts": ("2606:2800:220:1::",)},
        {"hosts": ("api.vendor.example:443",)},  # a port
        {"hosts": ("api..vendor.example",)},  # not a name the resolver could encode
        {"hosts": ("a" * 64 + ".vendor.example",)},
        {"infrastructure": ("*.internal",)},
        {"infrastructure": (" db",)},
        {"infrastructure": ("",)},
        {"infrastructure": ("db..internal",)},
        {"infrastructure": ("db:5432",)},
    ],
)
def test_a_guard_declaration_is_exact(kwargs: dict[str, tuple[str, ...]]) -> None:
    with pytest.raises(ValueError, match="EgressGuard"):
        EgressGuard(**kwargs)


def test_a_malformed_network_is_refused_at_declaration() -> None:
    with pytest.raises(ValueError):
        EgressGuard(infrastructure=("10.0.0.0/33",))


def test_installing_replaces_the_guard_and_uninstalling_makes_the_hook_inert() -> None:
    assert installed_egress_guard() is None
    first = EgressGuard(hosts=(_VENDOR,))
    install_egress_guard(first)
    assert installed_egress_guard() is first
    second = EgressGuard(hosts=("other.example",))
    install_egress_guard(second)
    assert installed_egress_guard() is second
    assert guard_module._hook_registered is True
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.getaddrinfo", _VENDOR, 443, 0, 0, 0)

    uninstall_egress_guard()
    assert installed_egress_guard() is None
    sys.audit("socket.getaddrinfo", "anything.example", 443, 0, 0, 0)
    sys.audit("socket.connect", None, (CLOUD_METADATA_ADDRESS, 80))


def test_the_guard_is_public_surface() -> None:
    assert {
        "EgressGuard",
        "EgressGuardUnsupportedError",
        "INFRASTRUCTURE_REFRESH_SECONDS",
        "install_egress_guard",
        "installed_egress_guard",
        "uninstall_egress_guard",
    } <= set(egress.__all__)
