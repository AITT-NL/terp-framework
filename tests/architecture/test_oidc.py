"""Pluggable SSO/OIDC capability (ADR 0058): protocol, validation, and router coverage.

A fake IdP lives entirely in-process: a real RSA keypair signs ID tokens, and a
handler serves the discovery document, the JWKS, and the token endpoint — so the full
Authorization Code + PKCE flow (and every fail-closed validation branch: bad
signature, wrong audience/issuer, expired, nonce mismatch, replayed state, unknown
provider, refused identity) is proven without a network.

The handler is reached through the **egress** capability's ``sender`` seam, so every
test here runs the real :class:`~terp.capabilities.egress.EgressClient` — its scheme
check, its allowlist, its SSRF denylist and its address pinning — with only the socket
replaced. The ``resolve`` seam is injected for the same reason and is not optional: a
test that let a name go to real DNS would fail to resolve ``.test`` and be refused,
and several of the assertions below would then pass for that reason instead of the
one they are written for.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.core import (
    Principal,
    Roles,
    encrypt_config,
    get_session,
)
from terp.core.app import register_error_handlers
from terp.core.config import settings

from terp.capabilities.auth import LoginThrottle, decode_access_token
from terp.capabilities.egress import (
    EgressAttempt,
    EgressFailedError,
    EgressResponse,
    PinnedTarget,
    Sender,
)
from terp.capabilities.oidc import (
    InMemoryStateStore,
    OIDCClaims,
    OIDCClient,
    OIDCProviderConfig,
    ProviderUnavailableError,
    build_oidc_module,
    build_oidc_router,
    code_challenge_s256,
    generate_code_verifier,
)
from terp.capabilities.oidc.client import MAX_RESPONSE_BYTES
from terp.capabilities.oidc.router import _throttle_key
from terp.core.errors import AppError

_KEY = "terp-oidc-test-secret-key-0123456789abcdef"
_ISSUER = "https://idp.example.test"
_CLIENT_ID = "terp-test-client"
_KID = "test-key-1"
#: Every provider host resolves here unless a test says otherwise — a public address,
#: so the denylist is satisfied and what a test proves is what it set out to prove.
_PUBLIC_IP = "93.184.216.34"


# --------------------------------------------------------------------------- #
# the fake IdP
# --------------------------------------------------------------------------- #
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(public_key, kid: str) -> dict:
    entry = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    entry.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return entry


def _sender_for(handler: Callable[[httpx.Request], httpx.Response]) -> Sender:
    """Adapt a plain ``httpx.Request -> httpx.Response`` handler to the egress seam.

    It honours ``max_response_bytes`` because a conforming transport does: the real one
    counts bytes as they arrive and raises :class:`EgressFailedError`. That the real one
    actually counts is proven in ``test_egress.py``, where the transport lives; what the
    cap tests here prove is that this capability *declares* the bound and that exceeding
    it surfaces as the uniform 502 rather than a parse error. The comparison is ``>``,
    matching the transport exactly — an inclusive bound tested against a fake that
    rounded the other way would be a test of the fake.
    """

    def _send(
        target: PinnedTarget,
        method: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> EgressResponse:
        response = handler(
            httpx.Request(method, target.url, content=body, headers=dict(headers))
        )
        content = response.content
        if len(content) > max_response_bytes:
            raise EgressFailedError(
                "The upstream response was larger than this application accepts.",
                log_context={"host": target.host, "limit": max_response_bytes},
            )
        return EgressResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=content,
        )

    return _send


class FakeIdP:
    """A configurable in-process IdP, reached through the egress ``sender`` seam."""

    def __init__(self, *, issuer: str = _ISSUER) -> None:
        self.issuer = issuer
        self.discovery = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/keys",
        }
        self.jwks = {"keys": [_jwk(_PRIVATE_KEY.public_key(), _KID)]}
        self.token_status = 200
        self.token_body: dict | str = {}
        self.discovery_status = 200
        self.jwks_payloads: list[dict] | None = None  # a queue, for rotation tests
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(self.discovery_status, json=self.discovery)
        if path.endswith("/keys"):
            payload = self.jwks
            if self.jwks_payloads:
                payload = self.jwks_payloads.pop(0)
            return httpx.Response(200, json=payload)
        if path.endswith("/token"):
            if isinstance(self.token_body, str):
                return httpx.Response(self.token_status, text=self.token_body)
            return httpx.Response(self.token_status, json=self.token_body)
        raise AssertionError(f"unexpected IdP request: {request.url}")  # pragma: no cover

    @property
    def sender(self) -> Sender:
        """This IdP as an egress transport (the socket, and nothing above it)."""
        return _sender_for(self.handler)

    @staticmethod
    def resolve(host: str) -> list[str]:
        """Name resolution for the suite: one public address, no DNS."""
        return [_PUBLIC_IP]

    def id_token(
        self,
        *,
        nonce: str,
        key=_PRIVATE_KEY,
        kid: str = _KID,
        **overrides,
    ) -> str:
        now = datetime.datetime.now(datetime.UTC)
        claims: dict = {
            "iss": self.issuer,
            "aud": _CLIENT_ID,
            "sub": "subject-1",
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
            "nonce": nonce,
            "email": "sso@acme.test",
            "email_verified": True,
            "name": "S. So",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _config(**overrides) -> OIDCProviderConfig:
    values: dict = {
        "name": "idp",
        "issuer": _ISSUER,
        "client_id": _CLIENT_ID,
        "client_secret": "s3cret-dev-value",
        "redirect_uri": "https://app.example.test/auth/callback/idp",
    }
    values.update(overrides)
    return OIDCProviderConfig(**values)


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture
def client(idp: FakeIdP) -> OIDCClient:
    return OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)


# --------------------------------------------------------------------------- #
# provider config — fail-fast validation
# --------------------------------------------------------------------------- #
def test_config_accepts_a_valid_provider() -> None:
    config = _config()
    assert config.scopes == ("openid", "email", "profile")


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Bad Name"},
        {"scopes": ("email", "profile")},
        {"issuer": "ldap://idp.example.test"},
        {"redirect_uri": "not-a-url"},
        {"client_id": ""},
    ],
)
def test_config_refuses_invalid_shapes(overrides: dict) -> None:
    with pytest.raises(ValueError):
        _config(**overrides)


def test_config_requires_https_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    with pytest.raises(ValueError, match="https in production"):
        _config(issuer="http://idp.example.test")
    with pytest.raises(ValueError, match="https in production"):
        _config(redirect_uri="http://app.example.test/cb")
    _config()  # https everywhere is accepted


def test_the_https_verdict_is_answerable_without_being_in_production() -> None:
    """A production refusal that exists only inside a production branch is unaskable.

    The constructor's raise is the enforcement, not the answer: nothing else can ask
    "would this configuration boot in production" from a dev machine or a CI runner,
    which is how a tree carries a green pre-ship gate into a deployment that will not
    start. `production_problems()` is the environment-independent answer, the same shape
    `ControlPlane` already exposes for the refusals the gate does reach.
    """
    assert _config().production_problems() == []
    plaintext = _config(issuer="http://idp.example.test")
    assert plaintext.production_problems() == [
        "OIDC provider 'idp' issuer must be https in production "
        "(a plaintext redirect leaks the authorization code)"
    ]
    both = _config(
        issuer="http://idp.example.test", redirect_uri="http://app.example.test/cb"
    )
    assert len(both.production_problems()) == 2, "each plaintext URL is its own problem"


def test_a_plaintext_provider_outside_production_is_permitted_but_never_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Permissive in the inner loop, never quiet — the asymmetry ADR 0128 names.

    Before this, the state was completely silent outside production: no warning, no
    verdict, nothing in any dev run or CI log. The first mention of it was the
    production boot that refused, which is the failure ADR 0128 exists to end, one
    layer out from the control-plane declarations that lane reads.
    """
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.oidc.config"):
        _config(issuer="http://idp.example.test")
    assert "PLAINTEXT" in caplog.text
    assert "REFUSED" in caplog.text, "the dev warning must say what production does"
    assert "idp" in caplog.text, "...and which provider it is about"


# --------------------------------------------------------------------------- #
# state store — single-use, expiring, provider-bound
# --------------------------------------------------------------------------- #
def test_state_round_trips_once_and_only_once() -> None:
    store = InMemoryStateStore()
    state, pending = store.issue("idp")
    assert store.consume(state, "idp") == pending
    assert store.consume(state, "idp") is None  # single-use: a replay finds nothing


def test_state_refuses_unknown_and_cross_provider() -> None:
    store = InMemoryStateStore()
    state, _ = store.issue("idp")
    assert store.consume("not-a-state", "idp") is None
    assert store.consume(state, "other") is None  # a cross-provider splice is refused


def test_state_expires_and_is_pruned(monkeypatch: pytest.MonkeyPatch) -> None:
    import terp.capabilities.oidc.state as state_mod

    now = [datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)]
    monkeypatch.setattr(state_mod, "_utc_now", lambda: now[0])
    store = InMemoryStateStore(ttl=datetime.timedelta(minutes=10))
    stale, _ = store.issue("idp")
    now[0] += datetime.timedelta(minutes=11)
    fresh, _ = store.issue("idp")  # issue prunes the aged-out entries
    assert stale not in store._pending
    assert fresh in store._pending
    assert store.consume(stale, "idp") is None  # expired (and already pruned)
    now[0] += datetime.timedelta(minutes=11)
    assert store.consume(fresh, "idp") is None  # expired but not yet pruned: still refused


def test_pkce_challenge_is_the_rfc7636_s256_vector() -> None:
    # RFC 7636 appendix B: the spec's own verifier/challenge pair.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert len(generate_code_verifier()) >= 43  # RFC 7636 §4.1 minimum entropy


# --------------------------------------------------------------------------- #
# discovery + JWKS
# --------------------------------------------------------------------------- #
def test_discovery_is_fetched_once_and_cached(idp: FakeIdP, client: OIDCClient) -> None:
    assert client.discovery()["token_endpoint"] == f"{_ISSUER}/token"
    assert client.discovery()["jwks_uri"] == f"{_ISSUER}/keys"
    assert len(idp.requests) == 1


def test_discovery_refuses_an_issuer_mismatch(idp: FakeIdP, client: OIDCClient) -> None:
    idp.discovery["issuer"] = "https://evil.example.test"  # IdP mix-up defense
    with pytest.raises(ProviderUnavailableError):
        client.discovery()


def test_discovery_refuses_a_missing_endpoint(idp: FakeIdP, client: OIDCClient) -> None:
    del idp.discovery["token_endpoint"]
    with pytest.raises(ProviderUnavailableError):
        client.discovery()


def test_discovery_maps_transport_and_status_failures_to_502(idp: FakeIdP) -> None:
    idp.discovery_status = 500
    with pytest.raises(ProviderUnavailableError):
        OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve).discovery()

    def _explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    down = OIDCClient(_config(), sender=_sender_for(_explode), resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        down.discovery()


def test_a_document_that_is_not_json_at_all_is_a_502(idp: FakeIdP) -> None:
    """A provider answering 200 with something that will not parse is still an outage.

    This behaviour was never actually exercised. The previous client caught the
    transport error and the parse error in a single ``except (httpx.HTTPError,
    ValueError)``, so the transport test covered the line and no test ever had to serve
    a malformed document. Splitting them — a refusal by this application's own address
    policy is not the same event as a body that will not parse, and only one of them
    says anything about the provider — is what made the gap visible.

    A captive portal or a proxy error page is the realistic shape: HTTP 200, HTML body.
    """

    def _garbage(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    client = OIDCClient(_config(), sender=_sender_for(_garbage), resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.discovery()


def test_discovery_refuses_a_non_object_document(idp: FakeIdP) -> None:
    def _array(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = OIDCClient(_config(), sender=_sender_for(_array), resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.discovery()


def test_an_oversized_provider_response_is_refused_rather_than_read(idp: FakeIdP) -> None:
    """An unbounded read is an outage the provider gets to declare.

    The timeout does not help: a body that keeps arriving keeps the connection busy, so
    the worker's memory is what runs out. The counting now belongs to the egress
    transport and is proven there; what is proven here is that this capability declares
    the bound on its policy and that being over it is the uniform 502.
    """

    def _flood(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

    client = OIDCClient(_config(), sender=_sender_for(_flood), resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.discovery()


def test_a_response_at_the_cap_is_still_served(idp: FakeIdP) -> None:
    """The bound is a ceiling, not a margin: exactly at the cap must still work.

    On the boundary deliberately — an off-by-one in the *wiring* (a policy handed one
    byte less than the constant says) refuses a document that is within the documented
    allowance, and the failure would look like a provider outage. The transport's own
    boundary is pinned separately, in ``test_egress.py``.
    """
    document = dict(idp.discovery)
    document["_pad"] = ""
    document["_pad"] = "x" * (
        MAX_RESPONSE_BYTES - len(json.dumps(document).encode("utf-8"))
    )

    def _exact(_request: httpx.Request) -> httpx.Response:
        body = json.dumps(document).encode("utf-8")
        assert len(body) == MAX_RESPONSE_BYTES
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    client = OIDCClient(_config(), sender=_sender_for(_exact), resolve=idp.resolve)
    assert client.discovery()["issuer"] == _ISSUER


# --------------------------------------------------------------------------- #
# the address policy: whose host is it?
# --------------------------------------------------------------------------- #
def test_the_issuer_host_may_be_private_and_a_host_the_document_named_may_not() -> None:
    """On-premises SSO is a deployment shape; a document steering the server is not.

    The operator configured the issuer, so an IdP inside the network is something they
    said. Every other host reaching the client was named by the **discovery document** —
    that is, by the far end — and a party that can edit its own document must not
    thereby be able to aim this server at an internal service or a metadata endpoint.

    One resolver answers ``10.0.0.5`` for everything, so the only thing separating the
    two outcomes below is whose host it is.
    """
    idp = FakeIdP()
    idp.discovery["jwks_uri"] = "https://keys.elsewhere.test/keys"
    client = OIDCClient(_config(), sender=idp.sender, resolve=lambda _host: ["10.0.0.5"])

    assert client.discovery()["issuer"] == _ISSUER  # the operator's own host: permitted

    with pytest.raises(ProviderUnavailableError):  # a host the document introduced
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")


def test_an_https_issuer_does_not_admit_an_http_endpoint(idp: FakeIdP) -> None:
    """A discovery document cannot downgrade the connection the operator configured.

    The token endpoint is where the client secret goes, so an ``http`` one named by the
    provider would put it on the wire in clear text.
    """
    idp.discovery["token_endpoint"] = "http://idp.example.test/token"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.exchange_code(code="c", code_verifier="v", client_secret="s")


def test_a_plain_http_issuer_on_a_private_address_still_works() -> None:
    """The setup people develop against: a local IdP, plain http, on loopback.

    Both relaxations at once, and both follow from the same fact — the operator named
    this issuer. A capability that refused this would be secure and unusable, and would
    be worked around rather than configured.
    """
    issuer = "http://localhost:8080/realms/dev"
    idp = FakeIdP(issuer=issuer)
    client = OIDCClient(
        _config(issuer=issuer), sender=idp.sender, resolve=lambda _host: ["127.0.0.1"]
    )
    assert client.discovery()["issuer"] == issuer


def test_an_endpoint_that_is_not_a_url_is_a_502(idp: FakeIdP) -> None:
    """There is no host to hold to an address policy, so it is refused, not attempted."""
    idp.discovery["jwks_uri"] = "not-a-url"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")


def test_a_token_endpoint_that_is_not_a_url_is_a_502(idp: FakeIdP) -> None:
    """The same guard on the POST path — ``discovery()`` only checks the key is present."""
    idp.discovery["token_endpoint"] = "not-a-url"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.exchange_code(code="c", code_verifier="v", client_secret="s")


def test_an_endpoint_that_does_not_parse_at_all_is_a_502(idp: FakeIdP) -> None:
    """``urlsplit`` does not fail quietly on a malformed URL — it raises.

    The two tests above serve ``"not-a-url"``, which parses fine and simply has no host.
    An unterminated IPv6 literal is the other shape, and it does not return: ``urlsplit``
    raises ``ValueError("Invalid IPv6 URL")`` before ``.hostname`` is ever reached. Both
    endpoints come out of a document the provider wrote rather than out of an operator's
    configuration, so the difference between the two decided whether a broken discovery
    document left as this capability's uniform 502 or as a bare, untyped 500.
    """
    idp.discovery["jwks_uri"] = "https://[::1"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")

    idp.discovery["token_endpoint"] = "https://[::1"
    token_client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        token_client.exchange_code(code="c", code_verifier="v", client_secret="s")


def test_an_endpoint_host_the_address_policy_refuses_is_a_502(idp: FakeIdP) -> None:
    """``EgressPolicy`` holds an exact hostname, and refuses one it cannot hold.

    A `*` in the host makes the allowlist entry a pattern, which the policy rejects by
    construction — correctly, since an allowlist that silently accepted a wildcard would
    be no allowlist. But the policy is built from a host the PROVIDER named, so that
    refusal is reachable from a discovery document, and it arrived as a `ValueError` out
    of a constructor rather than as this capability's declared outcome.
    """
    idp.discovery["jwks_uri"] = "https://keys.*.example.test/keys"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    with pytest.raises(ProviderUnavailableError):
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")


def test_the_router_hands_its_egress_seams_to_the_client_it_builds(idp: FakeIdP) -> None:
    """A seam wired at the composition root has to survive the trip to the client.

    Worth its own test because the failure is silent: an application that wires metering
    through ``build_oidc_module`` and then sees no attempts cannot tell that from a
    provider it never called. The client-level observer test below cannot catch it
    either — it builds its own client and never goes through the router at all.
    """
    seen: list[EgressAttempt] = []
    app, _store = _sso_app(idp, lambda _s, _c: None, observer=seen.append)

    # ``/authorize`` reads the discovery document, so exactly one attempt goes out.
    assert TestClient(app).get("/oidc/idp/authorize").status_code == 200
    assert [attempt.host for attempt in seen] == ["idp.example.test"]


def test_every_provider_call_reaches_the_egress_observer(idp: FakeIdP) -> None:
    """Metering and egress auditing attach here, and an SSO login is worth metering.

    This is what routing through the capability buys beyond the shared transport: the
    hook exists for every outbound call in the platform, so provider traffic stops being
    the one kind that no observer could see.
    """
    seen: list[EgressAttempt] = []
    client = OIDCClient(
        _config(), sender=idp.sender, resolve=idp.resolve, observer=seen.append
    )
    client.discovery()

    assert [attempt.host for attempt in seen] == ["idp.example.test"]
    assert seen[0].method == "GET"
    assert seen[0].status_code == 200
    assert seen[0].refused is False


def test_jwks_rotation_refetches_once_for_an_unknown_kid(idp: FakeIdP, client: OIDCClient) -> None:
    # First JWKS response carries only a stale key; the refetch carries the new one.
    idp.jwks_payloads = [
        {"keys": [_jwk(_OTHER_KEY.public_key(), "stale-key")]},
        {"keys": [_jwk(_PRIVATE_KEY.public_key(), _KID)]},
    ]
    claims = client.validate_id_token(idp.id_token(nonce="n1"), nonce="n1")
    assert claims.subject == "subject-1"


def test_jwks_kid_never_found_is_a_401(idp: FakeIdP, client: OIDCClient) -> None:
    idp.jwks = {"keys": [_jwk(_OTHER_KEY.public_key(), "some-other-kid")]}
    with pytest.raises(AppError) as excinfo:
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")
    assert excinfo.value.status_code == 401


def test_jwks_malformed_set_is_a_502(idp: FakeIdP, client: OIDCClient) -> None:
    idp.jwks = {"keys": []}  # PyJWKSet refuses an empty set
    with pytest.raises(ProviderUnavailableError):
        client.validate_id_token(idp.id_token(nonce="n"), nonce="n")


def test_token_without_kid_or_unparsable_is_a_401(client: OIDCClient) -> None:
    with pytest.raises(AppError) as excinfo:
        client.validate_id_token("garbage.token.value", nonce="n")
    assert excinfo.value.status_code == 401
    no_kid = jwt.encode({"sub": "x"}, _PRIVATE_KEY, algorithm="RS256")  # no kid header
    with pytest.raises(AppError) as excinfo:
        client.validate_id_token(no_kid, nonce="n")
    assert excinfo.value.status_code == 401


# --------------------------------------------------------------------------- #
# the authorize URL — code flow + PKCE only
# --------------------------------------------------------------------------- #
def test_authorization_url_carries_only_code_flow_pkce_parameters(client: OIDCClient) -> None:
    url = client.authorization_url(state="st", nonce="no", code_challenge="ch")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{_ISSUER}/authorize"
    assert params == {
        "response_type": ["code"],  # never implicit/hybrid (ADR 0058)
        "client_id": [_CLIENT_ID],
        "redirect_uri": ["https://app.example.test/auth/callback/idp"],
        "scope": ["openid email profile"],
        "state": ["st"],
        "nonce": ["no"],
        "code_challenge": ["ch"],
        "code_challenge_method": ["S256"],
    }


def test_authorization_url_appends_to_an_endpoint_with_a_query(idp: FakeIdP) -> None:
    idp.discovery["authorization_endpoint"] = f"{_ISSUER}/authorize?tenant=t1"
    client = OIDCClient(_config(), sender=idp.sender, resolve=idp.resolve)
    url = client.authorization_url(state="s", nonce="n", code_challenge="c")
    assert "?tenant=t1&" in url


# --------------------------------------------------------------------------- #
# the code exchange
# --------------------------------------------------------------------------- #
def test_exchange_posts_the_code_flow_form_and_returns_the_id_token(
    idp: FakeIdP, client: OIDCClient
) -> None:
    idp.token_body = {"id_token": "the-token", "access_token": "idp-access-ignored"}
    token = client.exchange_code(code="c0de", code_verifier="v", client_secret="s")
    assert token == "the-token"
    form = parse_qs(idp.requests[-1].content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["c0de"]
    assert form["code_verifier"] == ["v"]
    assert form["client_secret"] == ["s"]
    assert form["redirect_uri"] == ["https://app.example.test/auth/callback/idp"]
    # Declared rather than inferred, now that the body reaches the transport as bytes:
    # nothing derives a content type from the argument any more, and a token endpoint
    # handed a form POST without one is entitled to refuse it.
    assert (
        idp.requests[-1].headers["content-type"] == "application/x-www-form-urlencoded"
    )


def test_exchange_maps_refusal_transport_and_malformed_bodies(
    idp: FakeIdP, client: OIDCClient
) -> None:
    idp.token_status = 400  # a refused / replayed code is an auth failure, not an outage
    with pytest.raises(AppError) as excinfo:
        client.exchange_code(code="bad", code_verifier="v", client_secret="s")
    assert excinfo.value.status_code == 401

    idp.token_status = 200
    idp.token_body = {"access_token": "only"}  # no id_token
    with pytest.raises(AppError) as excinfo:
        client.exchange_code(code="c", code_verifier="v", client_secret="s")
    assert excinfo.value.status_code == 401

    idp.token_body = "not json"
    with pytest.raises(ProviderUnavailableError):
        client.exchange_code(code="c", code_verifier="v", client_secret="s")


def test_exchange_transport_failure_is_a_502(idp: FakeIdP) -> None:
    calls = {"n": 0}

    def _flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            raise httpx.ConnectError("down")
        return idp.handler(request)

    client = OIDCClient(_config(), sender=_sender_for(_flaky), resolve=idp.resolve)
    del calls
    with pytest.raises(ProviderUnavailableError):
        client.exchange_code(code="c", code_verifier="v", client_secret="s")


# --------------------------------------------------------------------------- #
# ID-token validation — every branch fails closed to the uniform 401
# --------------------------------------------------------------------------- #
def test_validate_accepts_a_fully_valid_token(idp: FakeIdP, client: OIDCClient) -> None:
    claims = client.validate_id_token(idp.id_token(nonce="n1"), nonce="n1")
    assert claims == OIDCClaims(
        issuer=_ISSUER,
        subject="subject-1",
        email="sso@acme.test",
        email_verified=True,
        name="S. So",
        raw=claims.raw,
    )
    assert claims.raw["aud"] == _CLIENT_ID


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": _OTHER_KEY},  # signed by a key outside the JWKS entry for this kid
        {"aud": "someone-else"},
        {"iss": "https://evil.example.test"},
        {"exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)},
        {"exp": None},  # exp is required
        {"sub": None},  # sub is required
        {"sub": 42},  # non-string subject
        {"sub": ""},  # empty subject
    ],
)
def test_validate_refuses_a_tampered_token(
    idp: FakeIdP, client: OIDCClient, overrides: dict
) -> None:
    key = overrides.pop("key", _PRIVATE_KEY)
    token = idp.id_token(nonce="n1", key=key, **overrides)
    with pytest.raises(AppError) as excinfo:
        client.validate_id_token(token, nonce="n1")
    assert excinfo.value.status_code == 401


def test_validate_refuses_a_nonce_mismatch(idp: FakeIdP, client: OIDCClient) -> None:
    token = idp.id_token(nonce="other-flow")
    with pytest.raises(AppError) as excinfo:
        client.validate_id_token(token, nonce="n1")
    assert excinfo.value.status_code == 401


def test_validate_normalizes_untrusted_optional_claims(idp: FakeIdP, client: OIDCClient) -> None:
    token = idp.id_token(nonce="n", email=123, email_verified="true", name=99)
    claims = client.validate_id_token(token, nonce="n")
    # A non-string email / name and a non-boolean email_verified never pass through:
    # provisioning decisions only ever see typed, verified values.
    assert claims.email is None
    assert claims.email_verified is False
    assert claims.name is None


# --------------------------------------------------------------------------- #
# the router — construction fail-fast + the wired flow
# --------------------------------------------------------------------------- #
def test_router_construction_refuses_bad_registries() -> None:
    resolver = lambda session, claims: None  # noqa: E731
    with pytest.raises(ValueError, match="at least one"):
        build_oidc_router([], resolver)
    with pytest.raises(ValueError, match="duplicate"):
        build_oidc_router([_config(), _config()], resolver)


def test_router_construction_refuses_a_sealed_secret_with_no_resolver() -> None:
    settings.SECRET_KEY = _KEY
    sealed = _config(client_secret=encrypt_config("the-real-secret"))
    with pytest.raises(ValueError, match="sealed client_secret"):
        build_oidc_router([sealed], lambda session, claims: None)


def _sso_app(
    idp: FakeIdP,
    resolver,
    *,
    config: OIDCProviderConfig | None = None,
    **kwargs,
) -> tuple[FastAPI, InMemoryStateStore]:
    settings.SECRET_KEY = _KEY
    store = InMemoryStateStore()
    module = build_oidc_module(
        [config if config is not None else _config()],
        resolver,
        state_store=store,
        sender=idp.sender,
        resolve=idp.resolve,
        **kwargs,
    )
    assert module.name == "oidc"
    assert module.policy.public  # explicit Policy.public, like /login
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(module.router, prefix="/oidc")
    app.dependency_overrides[get_session] = lambda: None
    return app, store


def _begin_flow(client: TestClient, idp: FakeIdP) -> tuple[str, str]:
    """Drive /authorize; return ``(state, nonce)`` as the IdP would see them."""
    body = client.get("/oidc/idp/authorize").json()
    assert body["provider"] == "idp"
    params = parse_qs(urlparse(body["authorization_url"]).query)
    return params["state"][0], params["nonce"][0]


def test_full_code_flow_mints_a_terp_token_not_an_idp_one(idp: FakeIdP) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    seen: dict = {}

    def resolver(_session, claims: OIDCClaims) -> Principal:
        seen["claims"] = claims
        return principal

    app, _ = _sso_app(idp, resolver)
    http = TestClient(app)
    state, nonce = _begin_flow(http, idp)
    idp.token_body = {"id_token": idp.id_token(nonce=nonce), "access_token": "idp-secret"}

    response = http.post("/oidc/idp/callback", json={"code": "c0de", "state": state})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    claims = decode_access_token(body["access_token"])  # a *Terp* token
    assert claims.subject == principal.id
    assert claims.role.rank == int(Roles.EDITOR)
    assert "idp-secret" not in response.text  # the IdP's tokens never leave
    assert seen["claims"].subject == "subject-1"
    assert "set-cookie" not in response.headers  # no refresh seam wired -> no cookie


def test_callback_signs_tenant_and_epoch_and_sets_the_refresh_cookie(idp: FakeIdP) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    tenant = uuid.uuid4()
    app, _ = _sso_app(
        idp,
        lambda _s, _c: principal,
        tenant_resolver=lambda _s, _p: tenant,
        token_version_resolver=lambda _s, _p: 7,
        refresh_issuer=lambda _s, _uid: "raw-refresh-token",
    )
    http = TestClient(app)
    state, nonce = _begin_flow(http, idp)
    idp.token_body = {"id_token": idp.id_token(nonce=nonce)}

    response = http.post("/oidc/idp/callback", json={"code": "c", "state": state})

    claims = decode_access_token(response.json()["access_token"])
    assert claims.tenant == tenant
    assert claims.token_version == 7  # ADR 0031: revocable from the first mint
    assert settings.REFRESH_COOKIE_NAME in response.cookies  # ADR 0054

def test_unknown_provider_is_a_404_on_both_routes(idp: FakeIdP) -> None:
    app, _ = _sso_app(idp, lambda _s, _c: None)
    http = TestClient(app)
    assert http.get("/oidc/ghost/authorize").status_code == 404
    assert http.post("/oidc/ghost/callback", json={"code": "c", "state": "s"}).status_code == 404


def test_replayed_or_unknown_state_is_refused_and_counted(idp: FakeIdP) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    throttle = LoginThrottle(max_attempts=2)
    app, _ = _sso_app(idp, lambda _s, _c: principal, throttle=throttle)
    http = TestClient(app)

    assert http.post("/oidc/idp/callback", json={"code": "c", "state": "ghost"}).status_code == 401

    state, nonce = _begin_flow(http, idp)
    idp.token_body = {"id_token": idp.id_token(nonce=nonce)}
    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 200
    # the state was consumed: replaying the exact same callback is refused...
    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 401
    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 401
    # ...and the failures crossed the throttle threshold: the source is locked out (429).
    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 429


def test_a_refused_identity_is_the_uniform_401(idp: FakeIdP) -> None:
    app, _ = _sso_app(idp, lambda _s, _c: None)  # the seam refuses (no link, no JIT)
    http = TestClient(app)
    state, nonce = _begin_flow(http, idp)
    idp.token_body = {"id_token": idp.id_token(nonce=nonce)}
    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 401


def test_a_sealed_client_secret_is_resolved_through_the_app_seam(idp: FakeIdP) -> None:
    settings.SECRET_KEY = _KEY
    sealed = _config(client_secret=encrypt_config("the-real-secret"))
    principal = Principal(id=uuid.uuid4(), role=Roles.VIEWER)
    unsealed: list[str] = []

    def secret_resolver(value: str) -> str:
        unsealed.append(value)
        return "the-real-secret"  # the app's single allowlisted decrypt site (ADR 0055)

    app, _ = _sso_app(
        idp, lambda _s, _c: principal, config=sealed, secret_resolver=secret_resolver
    )
    http = TestClient(app)
    state, nonce = _begin_flow(http, idp)
    idp.token_body = {"id_token": idp.id_token(nonce=nonce)}

    assert http.post("/oidc/idp/callback", json={"code": "c", "state": state}).status_code == 200
    assert unsealed == [sealed.client_secret]
    exchange = [r for r in idp.requests if r.url.path.endswith("/token")][-1]
    form = parse_qs(exchange.content.decode())
    assert form["client_secret"] == ["the-real-secret"]  # unsealed only at the exchange


def test_throttle_key_falls_back_when_the_request_has_no_client() -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [], "client": None})
    assert _throttle_key("idp", request) == "oidc:idp:anonymous"


def test_throttle_key_uses_the_centrally_resolved_client_ip() -> None:
    # The security stack's ClientIpMiddleware resolves the caller (honouring
    # trusted_proxy_hops) onto request.state; the throttle key must read that,
    # not the raw TCP peer, so a proxied deployment locks out the real client.
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("10.0.0.1", 80),
            "state": {"client_ip": "203.0.113.9"},
        }
    )
    assert _throttle_key("idp", request) == "oidc:idp:203.0.113.9"


# --------------------------------------------------------------------------- #
# the example app's wiring (dogfooding)
# --------------------------------------------------------------------------- #
def test_example_app_mounts_the_oidc_module() -> None:
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "example"))
    try:
        from app.main import build

        paths = set(build().openapi()["paths"])
    finally:
        sys.path.pop(0)
    assert "/api/v1/oidc/{provider}/authorize" in paths
    assert "/api/v1/oidc/{provider}/callback" in paths
