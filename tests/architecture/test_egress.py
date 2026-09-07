"""The egress capability: the declared way out of the process.

``no_raw_outbound_http`` refused a raw HTTP client in application code and sent the
author to "a declared capability with SSRF protection" — which did not exist. These
tests hold the capability that now does, and they are written the way the rule's own
argument runs: the allowlist, the SSRF denylist, the timeout and the egress record are
properties of a declaration, so a call site cannot decide any of them.

Almost every assertion here is a refusal. A guard is only worth what it says no to, and
the compliant cases exist mostly to prove the refusals are not simply "everything".
"""

from __future__ import annotations

import socket

import httpx
import pytest

from terp.capabilities.egress import (
    CLOUD_METADATA_ADDRESS,
    EgressAttempt,
    EgressClient,
    EgressFailedError,
    EgressPolicy,
    EgressRefusedError,
    EgressResponse,
    PinnedTarget,
    as_ip_literal,
    is_denied_address,
    resolve_host,
)
from terp.capabilities.egress.client import _httpx_sender

_PUBLIC = "93.184.216.34"


def _ok_sender(
    target: PinnedTarget,
    method: str,
    body: bytes | None,
    headers: object,
    timeout: float,
    cap: int,
) -> EgressResponse:
    return EgressResponse(status_code=200, headers={"x-seen": target.ip}, content=b"ok")


def _client(policy: EgressPolicy, **kwargs: object) -> EgressClient:
    kwargs.setdefault("sender", _ok_sender)
    kwargs.setdefault("resolve", lambda _host: [_PUBLIC])
    return EgressClient(policy, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# the denylist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # RFC 1918
        "172.16.0.1",  # RFC 1918
        "192.168.1.1",  # RFC 1918
        CLOUD_METADATA_ADDRESS,  # the one everybody means by "SSRF"
        "169.254.1.1",  # link-local generally
        "100.64.0.1",  # carrier-grade NAT
        "198.18.0.1",  # benchmarking
        "192.0.0.1",  # IETF assignments
        "0.0.0.0",  # noqa: S104 - the expected value of a denylist assertion, not a bind
        "224.0.0.1",  # multicast
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 — the classic bypass
        "::ffff:10.0.0.1",  # ... and again with private space
    ],
)
def test_denied_addresses(address: str) -> None:
    assert is_denied_address(address) is True


@pytest.mark.parametrize("address", [_PUBLIC, "8.8.8.8", "2606:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    """The denylist must not be "everything", or it would say nothing."""
    assert is_denied_address(address) is False


def test_as_ip_literal() -> None:
    assert as_ip_literal("127.0.0.1") == "127.0.0.1"
    assert as_ip_literal("::1") == "::1"
    assert as_ip_literal("example.com") is None


def test_resolve_host_returns_every_address_and_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _h, _p: [(0, 0, 0, "", (_PUBLIC, 0)), (0, 0, 0, "", ("8.8.8.8", 0))],
    )
    assert resolve_host("example.com") == [_PUBLIC, "8.8.8.8"]

    def _boom(_h: str, _p: object) -> list[object]:
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(OSError):
        resolve_host("example.com")


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
def test_a_policy_nobody_filled_in_permits_nothing() -> None:
    assert EgressPolicy().permits_anything is False
    assert EgressPolicy(allowed_hosts=("api.example.com",)).permits_anything is True


def test_the_allowlist_is_exact_not_a_suffix() -> None:
    policy = EgressPolicy(allowed_hosts=("api.example.com",))
    assert policy.permits_host("api.example.com") is True
    assert policy.permits_host("API.Example.COM") is True  # host names are case-insensitive
    assert policy.permits_host("evil-api.example.com") is False
    assert policy.permits_host("api.example.com.evil.test") is False


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"timeout_seconds": -1}, "timeout_seconds"),
        ({"max_response_bytes": 0}, "max_response_bytes"),
        ({"allowed_schemes": ()}, "allowed_schemes"),
        ({"allowed_hosts": ("*.example.com",)}, "wildcard"),
        ({"allowed_hosts": (" api.example.com ",)}, "lowercase hostnames"),
        ({"allowed_hosts": ("API.example.com",)}, "lowercase hostnames"),
        ({"allowed_hosts": ("",)}, "lowercase hostnames"),
    ],
)
def test_a_policy_that_would_mislead_is_refused_at_construction(
    kwargs: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        EgressPolicy(**kwargs)


# --------------------------------------------------------------------------- #
# what the client refuses, and why
# --------------------------------------------------------------------------- #
def _reason(exc: EgressRefusedError) -> str:
    return str(exc.log_context.get("reason"))


def test_a_scheme_the_policy_does_not_declare() -> None:
    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)))
    with pytest.raises(EgressRefusedError) as caught:
        client.get("http://api.example.com/v1")
    assert _reason(caught.value) == "scheme"


def test_a_url_with_no_host() -> None:
    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)))
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https:///v1")
    assert _reason(caught.value) == "no_host"


def test_a_host_nobody_declared() -> None:
    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)))
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https://evil.example.com/v1")
    assert _reason(caught.value) == "host_not_allowed"


def test_a_declared_host_that_resolves_into_a_denied_range() -> None:
    """The allowlist and the denylist are both required, and neither implies the other."""
    client = _client(
        EgressPolicy(allowed_hosts=("internal.example.com",)),
        resolve=lambda _host: ["10.0.0.5"],
    )
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https://internal.example.com/v1")
    assert _reason(caught.value) == "denied_address"


def test_one_bad_address_among_several_refuses_the_whole_target() -> None:
    """Every address is checked, not the first: a name can return more than one."""
    client = _client(
        EgressPolicy(allowed_hosts=("mixed.example.com",)),
        resolve=lambda _host: [_PUBLIC, "127.0.0.1"],
    )
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https://mixed.example.com/v1")
    assert _reason(caught.value) == "denied_address"


def test_an_ip_literal_host_skips_dns_and_is_still_checked() -> None:
    def _never(_host: str) -> list[str]:  # pragma: no cover - must not be called
        raise AssertionError("an IP literal must not be resolved")

    client = _client(
        EgressPolicy(allowed_hosts=(CLOUD_METADATA_ADDRESS,)), resolve=_never
    )
    with pytest.raises(EgressRefusedError) as caught:
        client.get(f"https://{CLOUD_METADATA_ADDRESS}/latest/meta-data/")
    assert _reason(caught.value) == "denied_address"


def test_an_unresolvable_host_is_refused_not_attempted() -> None:
    def _boom(_host: str) -> list[str]:
        raise socket.gaierror("name resolution failed")

    client = _client(EgressPolicy(allowed_hosts=("gone.example.com",)), resolve=_boom)
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https://gone.example.com/v1")
    assert _reason(caught.value) == "unresolvable"


def test_a_host_that_resolves_to_nothing_is_refused() -> None:
    client = _client(
        EgressPolicy(allowed_hosts=("void.example.com",)), resolve=lambda _host: []
    )
    with pytest.raises(EgressRefusedError) as caught:
        client.get("https://void.example.com/v1")
    assert _reason(caught.value) == "unresolvable"


def test_allow_private_addresses_is_the_declared_way_to_reach_an_internal_target() -> None:
    """The opt-out exists, is a declaration, and is off unless someone wrote it."""
    policy = EgressPolicy(
        allowed_hosts=("internal.example.com",), allow_private_addresses=True
    )
    client = _client(policy, resolve=lambda _host: ["10.0.0.5"])
    assert client.get("https://internal.example.com/v1").status_code == 200


# --------------------------------------------------------------------------- #
# what it does when it does not refuse
# --------------------------------------------------------------------------- #
def test_the_connection_is_pinned_to_the_validated_address() -> None:
    """The whole point of resolving once: the socket cannot be re-pointed afterwards."""
    seen: list[PinnedTarget] = []

    def _capture(target: PinnedTarget, *args: object) -> EgressResponse:
        seen.append(target)
        return EgressResponse(200, {}, b"")

    client = _client(
        EgressPolicy(allowed_hosts=("api.example.com",)), sender=_capture
    )
    client.get("https://api.example.com/v1/rates")
    assert seen[0].url == "https://api.example.com/v1/rates"
    assert seen[0].host == "api.example.com"
    assert seen[0].ip == _PUBLIC


def test_the_policy_supplies_the_timeout_and_the_cap_not_the_call_site() -> None:
    seen: list[tuple[float, int]] = []

    def _capture(
        target: PinnedTarget, method: str, body: object, headers: object, timeout: float, cap: int
    ) -> EgressResponse:
        seen.append((timeout, cap))
        return EgressResponse(200, {}, b"")

    policy = EgressPolicy(
        allowed_hosts=("api.example.com",), timeout_seconds=2.5, max_response_bytes=1234
    )
    _client(policy, sender=_capture).get("https://api.example.com/")
    assert seen == [(2.5, 1234)]


def test_post_carries_the_body_and_the_method() -> None:
    seen: list[tuple[str, bytes | None]] = []

    def _capture(
        target: PinnedTarget, method: str, body: bytes | None, *args: object
    ) -> EgressResponse:
        seen.append((method, body))
        return EgressResponse(201, {}, b"")

    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)), sender=_capture)
    response = client.post("https://api.example.com/v1", body=b"{}")
    assert seen == [("POST", b"{}")]
    assert response.status_code == 201
    assert response.ok is True


def test_ok_is_the_2xx_band() -> None:
    assert EgressResponse(200, {}, b"").ok is True
    assert EgressResponse(299, {}, b"").ok is True
    assert EgressResponse(300, {}, b"").ok is False
    assert EgressResponse(500, {}, b"").ok is False


# --------------------------------------------------------------------------- #
# failures, and what they are allowed to say
# --------------------------------------------------------------------------- #
def test_a_transport_error_becomes_one_typed_failure_that_says_nothing() -> None:
    """The transport's text names hosts and ports; that is for the log, not the client."""

    def _boom(*args: object) -> EgressResponse:
        raise TimeoutError("connect to 10.0.0.5:443 timed out")

    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)), sender=_boom)
    with pytest.raises(EgressFailedError) as caught:
        client.get("https://api.example.com/")
    assert "10.0.0.5" not in caught.value.message
    assert caught.value.log_context["host"] == "api.example.com"
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_an_egress_failure_from_the_sender_is_not_re_wrapped() -> None:
    def _already_typed(*args: object) -> EgressResponse:
        raise EgressFailedError("The upstream response was too large.")

    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)), sender=_already_typed)
    with pytest.raises(EgressFailedError) as caught:
        client.get("https://api.example.com/")
    assert caught.value.__cause__ is None


# --------------------------------------------------------------------------- #
# the observability seam — where metering and egress auditing attach
# --------------------------------------------------------------------------- #
def test_every_attempt_is_observed_including_the_refusals() -> None:
    seen: list[EgressAttempt] = []
    policy = EgressPolicy(allowed_hosts=("api.example.com",))
    client = _client(policy, observer=seen.append, clock=iter([0.0, 0.5, 1.0, 3.0]).__next__)

    client.get("https://api.example.com/")
    with pytest.raises(EgressRefusedError):
        client.get("https://evil.example.com/")

    assert [(a.host, a.status_code, a.refused) for a in seen] == [
        ("api.example.com", 200, False),
        ("evil.example.com", None, True),
    ]
    assert seen[0].duration_seconds == 0.5
    assert seen[0].response_bytes == 2
    assert seen[0].method == "GET"


def test_a_failed_call_is_observed_too() -> None:
    seen: list[EgressAttempt] = []

    def _boom(*args: object) -> EgressResponse:
        raise TimeoutError("slow")

    client = _client(
        EgressPolicy(allowed_hosts=("api.example.com",)), sender=_boom, observer=seen.append
    )
    with pytest.raises(EgressFailedError):
        client.get("https://api.example.com/")
    assert [(a.host, a.status_code, a.refused) for a in seen] == [
        ("api.example.com", None, False)
    ]


def test_a_typed_failure_from_the_sender_is_observed() -> None:
    seen: list[EgressAttempt] = []

    def _typed(*args: object) -> EgressResponse:
        raise EgressFailedError("too big")

    client = _client(
        EgressPolicy(allowed_hosts=("api.example.com",)), sender=_typed, observer=seen.append
    )
    with pytest.raises(EgressFailedError):
        client.get("https://api.example.com/")
    assert len(seen) == 1


def test_an_observer_that_raises_does_not_change_what_happened() -> None:
    """Metering is not allowed to turn a completed call into a failed one."""

    def _bad_observer(_attempt: EgressAttempt) -> None:
        raise RuntimeError("the metrics backend is down")

    client = _client(
        EgressPolicy(allowed_hosts=("api.example.com",)), observer=_bad_observer
    )
    assert client.get("https://api.example.com/").status_code == 200

    # ... and a refusal is still the refusal, not the observer's error.
    with pytest.raises(EgressRefusedError):
        client.get("https://evil.example.com/")


def test_no_observer_is_fine() -> None:
    client = _client(EgressPolicy(allowed_hosts=("api.example.com",)))
    assert client.get("https://api.example.com/").status_code == 200
    assert client.policy.allowed_hosts == ("api.example.com",)


# --------------------------------------------------------------------------- #
# the default transport, driven through a mock so no socket is opened
# --------------------------------------------------------------------------- #
def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler: object) -> list[httpx.Request]:
    """Point httpx.Client at a MockTransport, and record what it was asked to send."""
    recorded: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)  # type: ignore[operator]

    real_client = httpx.Client

    def _factory(**kwargs: object) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(_record)
        return real_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "Client", _factory)
    return recorded


def test_the_default_transport_pins_the_address_and_keeps_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _mock_httpx(
        monkeypatch, lambda _r: httpx.Response(200, headers={"x": "y"}, content=b"body")
    )
    target = PinnedTarget(url="https://api.example.com/v1", host="api.example.com", ip=_PUBLIC)

    response = _httpx_sender(target, "GET", None, {"accept": "application/json"}, 3.0, 4096)

    assert response.status_code == 200
    assert response.content == b"body"
    assert response.headers["x"] == "y"
    # The socket goes to the validated address, while the Host header still names the
    # hostname — that pairing is the DNS-rebinding defence.
    assert recorded[0].url.host == _PUBLIC
    assert recorded[0].headers["host"] == "api.example.com"


def test_the_default_transport_sends_the_request_it_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body and the SNI extension must survive to the wire.

    They did not. The sender built a request carrying both and then sent a
    *different* one derived from a method and a URL, so every POST went out empty
    and every TLS handshake would have been negotiated against the pinned IP rather
    than the hostname — breaking certificate verification, which is the safe half of
    the pinning the function exists for. Neither showed up: the earlier tests sent a
    GET with no body and asserted on the URL host and the Host header, and both of
    those survive the mistake.
    """
    recorded = _mock_httpx(monkeypatch, lambda _r: httpx.Response(200, content=b"ok"))
    target = PinnedTarget(url="https://api.example.com/v1", host="api.example.com", ip=_PUBLIC)

    _httpx_sender(
        target, "POST", b'{"amount": 42}', {"content-type": "application/json"}, 3.0, 4096
    )

    sent = recorded[0]
    assert sent.method == "POST"
    assert sent.content == b'{"amount": 42}'
    assert sent.headers["content-type"] == "application/json"
    # TLS is verified against the hostname even though the socket goes to the IP.
    assert sent.extensions["sni_hostname"] == "api.example.com"
    assert sent.url.host == _PUBLIC
    assert sent.headers["host"] == "api.example.com"


def test_the_default_transport_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A followed redirect is a second target nobody validated."""
    _mock_httpx(
        monkeypatch,
        lambda _r: httpx.Response(302, headers={"location": "https://evil.example/"}),
    )
    target = PinnedTarget(url="https://api.example.com/v1", host="api.example.com", ip=_PUBLIC)

    response = _httpx_sender(target, "GET", None, {}, 3.0, 4096)

    assert response.status_code == 302
    assert response.ok is False


def test_the_default_transport_refuses_an_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_httpx(monkeypatch, lambda _r: httpx.Response(200, content=b"x" * 5000))
    target = PinnedTarget(url="https://api.example.com/v1", host="api.example.com", ip=_PUBLIC)

    with pytest.raises(EgressFailedError) as caught:
        _httpx_sender(target, "GET", None, {}, 3.0, 100)
    assert caught.value.log_context["limit"] == 100
