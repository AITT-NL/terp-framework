"""The egress guard: the declaration held at the socket, for every library (ADR 0177).

The egress client guards the calls made through it, and a vendor SDK makes its own. These
tests hold the process-wide half. A lookup of an undeclared name and a connection into a
denied range are refused wherever they come from: a real ``socket.getaddrinfo``, a real
``socket.connect``, or the audit events a library raises on the way to one.

Every refusal below happens before the network is touched. The audit hook runs ahead of
the lookup or the connect it audits, which is the property the guard rests on, so the
real-socket cases need no network at all.
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Iterator

import pytest

from terp.capabilities import egress
from terp.capabilities.egress import (
    CLOUD_METADATA_ADDRESS,
    INFRASTRUCTURE_REFRESH_SECONDS,
    EgressGuard,
    EgressPolicy,
    EgressRefusedError,
    install_egress_guard,
    installed_egress_guard,
    uninstall_egress_guard,
)
from terp.capabilities.egress import guard as guard_module

_VENDOR = "api.vendor.example"


@pytest.fixture(autouse=True)
def _inert_after_each_test() -> Iterator[None]:
    uninstall_egress_guard()
    yield
    uninstall_egress_guard()


def _refusal(excinfo: pytest.ExceptionInfo[EgressRefusedError]) -> str:
    return excinfo.value.log_context["reason"]


def test_an_undeclared_name_is_refused_before_it_resolves() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError) as refused:
        socket.getaddrinfo("internal-admin.corp.example", 443)
    assert _refusal(refused) == "undeclared_host"
    assert refused.value.log_context["control"] == "egress_guard"


def test_declared_names_resolve_as_written_and_localhost_always_does() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,), infrastructure=("db",)))
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


def test_a_real_connect_into_the_metadata_range_is_refused_before_it_is_made() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(EgressRefusedError) as refused:
            sock.connect((CLOUD_METADATA_ADDRESS, 80))
    assert _refusal(refused) == "denied_address"
    assert refused.value.log_context["address"] == CLOUD_METADATA_ADDRESS


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "172.18.0.3", "192.168.1.1", "127.0.0.1", "::1", "::ffff:127.0.0.1", "fe80::1"],
)
def test_every_denied_range_is_refused_at_the_connect(address: str) -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, (address, 443))


def test_a_public_address_connects() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    sys.audit("socket.connect", None, ("93.184.216.34", 443))
    sys.audit("socket.connect", None, ("2606:2800:220:1::", 443, 0, 0))


def test_a_connect_by_name_is_held_to_the_name_rule() -> None:
    install_egress_guard(EgressGuard(hosts=(_VENDOR,)))
    with pytest.raises(EgressRefusedError) as refused:
        sys.audit("socket.connect", None, ("internal.service", 80))
    assert _refusal(refused) == "undeclared_host"
    sys.audit("socket.connect", None, (_VENDOR.encode(), 443))


def test_datagrams_are_held_and_local_or_peerless_sockets_pass() -> None:
    install_egress_guard(EgressGuard())
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.sendto", None, (CLOUD_METADATA_ADDRESS, 53))
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.sendmsg", None, ("10.0.0.1", 53))
    sys.audit("socket.sendmsg", None, None)  # a connected socket names no peer
    sys.audit("socket.connect", None, "/run/postgresql/.s.PGSQL.5432")  # AF_UNIX
    sys.audit("socket.connect", None, (0, 0))  # a non-IP family (netlink-shaped)
    sys.audit("socket.connect", None)
    sys.audit("socket.bind", None, ("0.0.0.0", 8000))  # noqa: S104 - not a way out
    sys.audit("open", "/etc/hosts", "r", 0)


def test_declared_infrastructure_may_sit_on_private_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups: list[str] = []

    def resolver(name: str) -> list[str]:
        lookups.append(name)
        if name == "gone":
            raise OSError("no such host")
        return {"db": ["172.18.0.3"], "redis": ["::ffff:172.18.0.4"]}[name]

    clock = [100.0]
    monkeypatch.setattr(guard_module.time, "monotonic", lambda: clock[0])
    install_egress_guard(
        EgressGuard(infrastructure=("db", "redis", "gone", "10.1.0.0/16", "192.168.5.5")),
        resolver=resolver,
    )
    for address in ("10.1.2.3", "192.168.5.5"):  # networks and literals need no lookup
        sys.audit("socket.connect", None, (address, 5432))
    assert lookups == []

    sys.audit("socket.connect", None, ("172.18.0.3", 5432))  # resolved on the first miss
    sys.audit("socket.connect", None, ("172.18.0.4", 6379))  # a mapped answer, unwrapped
    assert sorted(lookups) == ["db", "gone", "redis"]

    with pytest.raises(EgressRefusedError):  # a neighbour on the same network is not infrastructure
        sys.audit("socket.connect", None, ("172.18.0.9", 80))
    assert len(lookups) == 3  # inside the window, a miss does not look again

    clock[0] += INFRASTRUCTURE_REFRESH_SECONDS
    with pytest.raises(EgressRefusedError):
        sys.audit("socket.connect", None, ("172.18.0.9", 80))
    assert len(lookups) == 6  # past it, one more resolution, then the same answer


def test_the_guard_a_policy_implies_keeps_internal_targets_internal() -> None:
    public = EgressPolicy(allowed_hosts=("api.rates.example", _VENDOR))
    internal = EgressPolicy(allowed_hosts=("ledger.internal",), allow_private_addresses=True)
    guard = EgressGuard.for_policies(
        public, internal, hosts=(_VENDOR, "sdk.vendor.example"), infrastructure=("db",)
    )
    assert guard.hosts == ("api.rates.example", _VENDOR, "sdk.vendor.example")
    assert guard.infrastructure == ("ledger.internal", "db")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hosts": ("API.vendor.example",)},
        {"hosts": ("*.vendor.example",)},
        {"hosts": ("vendor.example.",)},
        {"hosts": ("10.0.0.0/8",)},
        {"hosts": ("",)},
        {"infrastructure": ("*.internal",)},
        {"infrastructure": (" db",)},
        {"infrastructure": ("",)},
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
        "INFRASTRUCTURE_REFRESH_SECONDS",
        "install_egress_guard",
        "installed_egress_guard",
        "uninstall_egress_guard",
    } <= set(egress.__all__)
