"""The OIDC protocol client: discovery, JWKS, code exchange, ID-token validation.

One ``OIDCClient`` per configured provider. Endpoints and signing keys come from the
issuer's ``/.well-known/openid-configuration`` (fetched lazily, cached for the client's
lifetime); the JWKS is cached too and re-fetched **once** when a token names an unknown
``kid`` (key rotation). Validation is fail-closed (ADR 0058): asymmetric signature
algorithms only (``alg=none`` / HS* are never accepted), exact ``iss`` / ``aud`` /
``nonce`` matches, ``exp`` / ``iat`` required with bounded clock skew, and the discovery
document's ``issuer`` must equal the configured issuer (IdP mix-up defense). Every
validation failure is the uniform 401; an unreachable provider is a distinct 502 so
operators can tell an outage from an attack.

Every provider request leaves through the egress capability, so the SSRF denylist, the
address pinning, the bounded read, the refusal to follow a redirect and the egress
observer are one shared implementation rather than this module's own copy. What is
specific to OIDC is *which* address policy covers which host, and it is one sentence:
the issuer's own host may resolve into a private range — an operator who configures an
internal IdP has said so — and a host the discovery document introduced may not,
because the far end does not get to choose which network this server reaches into.
Tests inject the egress ``sender`` and ``resolve`` seams.
"""

from __future__ import annotations

import json
from threading import Lock
from typing import Any, Final
from urllib.parse import urlencode, urlsplit

import jwt

from terp.core import AppError, AuthenticationError

from terp.capabilities.egress import (
    EgressClient,
    EgressFailedError,
    EgressPolicy,
    EgressRefusedError,
    Observer,
    Resolver,
    Sender,
)
from terp.capabilities.oidc.config import OIDCClaims, OIDCProviderConfig

#: Asymmetric signature algorithms accepted on an ID token. ``alg=none`` and the
#: HS* (symmetric) family are excluded by construction: with HS* the "key" would be
#: the client secret, and a leaked secret could then forge identities.
ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256", "RS384", "RS512", "PS256", "ES256", "ES384")

#: Bounded clock skew for ``exp`` / ``iat`` validation, in seconds.
CLOCK_SKEW_LEEWAY_SECONDS = 60

#: The ceiling on a single provider response body, carried on this capability's
#: :class:`~terp.capabilities.egress.EgressPolicy` and enforced by the egress transport,
#: which reads in flight and never buffers whole past it. A discovery document is a couple
#: of kilobytes and a JWKS a few more, so this is generous by three orders of magnitude —
#: the point is that a bound *exists*. Without one, every provider read was as large as the
#: far end chose to make it: a hostile, compromised, or merely misconfigured issuer
#: answering a JWKS fetch with an endless body takes the worker's memory with it, and the
#: timeout does not help because the connection is never idle.
MAX_RESPONSE_BYTES: Final[int] = 1024 * 1024

_DISCOVERY_PATH = "/.well-known/openid-configuration"
_HTTP_TIMEOUT_SECONDS = 10.0


class ProviderUnavailableError(AppError):
    """502 — the identity provider could not be reached or answered malformed data."""

    status_code = 502
    code = "oidc_provider_unavailable"
    default_message = "The identity provider is unavailable; please try again."


class OIDCClient:
    """The protocol client for one configured provider."""

    def __init__(
        self,
        config: OIDCProviderConfig,
        *,
        sender: Sender | None = None,
        resolve: Resolver | None = None,
        observer: Observer | None = None,
    ) -> None:
        self._config = config
        self._sender = sender
        self._resolve = resolve
        self._observer = observer
        self._lock = Lock()
        self._discovery: dict[str, Any] | None = None
        self._jwks: jwt.PyJWKSet | None = None
        issuer = urlsplit(config.issuer)
        self._issuer_host = issuer.hostname or ""
        # A dev issuer may be plain http — the config only requires https in production —
        # and a policy that refused it would make the capability unusable in the setup
        # people actually develop against. The allowance follows the issuer's own scheme
        # rather than being a separate switch, so an https issuer can never have its
        # endpoints downgraded to http by whatever the discovery document says.
        self._schemes = ("https",) if issuer.scheme == "https" else ("https", "http")
        self._egress: dict[str, EgressClient] = {}

    @property
    def config(self) -> OIDCProviderConfig:
        return self._config

    def _egress_for(self, host: str) -> EgressClient:
        """The declared outbound client for one provider *host*, built once and cached.

        One client per host rather than one per provider, because the two differ in the
        only way that matters here: **the issuer's own host may resolve into a private
        range and no other host may.** The operator named the issuer, so an IdP on the
        internal network is a deployment shape rather than an anomaly — it is how
        on-premises SSO looks. Every other host reaching this function was named by the
        *discovery document*, i.e. by the far end, and a party that can edit its own
        discovery document must not thereby be able to aim this server at a metadata
        endpoint or an internal service.

        The allowlist is one host by construction, so it is a record of who this
        provider talks to rather than a constraint that refuses anything — the constraint
        is the address rule above. Saying so is better than implying an allowlist is
        doing work it cannot do: the endpoint hosts are not knowable before the document
        that names them has been read.
        """
        client = self._egress.get(host)
        if client is None:
            client = EgressClient(
                EgressPolicy(
                    allowed_hosts=(host,),
                    timeout_seconds=_HTTP_TIMEOUT_SECONDS,
                    max_response_bytes=MAX_RESPONSE_BYTES,
                    allow_private_addresses=host == self._issuer_host,
                    allowed_schemes=self._schemes,
                ),
                sender=self._sender,
                resolve=self._resolve,
                observer=self._observer,
            )
            self._egress[host] = client
        return client

    # ------------------------------------------------------------------ #
    # discovery + JWKS
    # ------------------------------------------------------------------ #
    def _get_json(self, url: str) -> dict[str, Any]:
        """GET *url* through egress and parse JSON; every failure is the uniform 502.

        A refusal and a failure collapse into one outcome on purpose. They differ in who
        is at fault — a refusal is this application's own address policy saying no to a
        host the provider named, a failure is the far end — and neither is something the
        person logging in can act on, so the distinction belongs in the log (where the
        egress errors carry it) and not in the response. The two documents this fetches,
        discovery and the JWKS, are read on a path a caller reaches by starting a login.
        """
        host = urlsplit(url).hostname
        if not host:
            # The provider named an endpoint that is not a URL. Refused rather than
            # attempted: there is no host to hold to an address policy.
            raise ProviderUnavailableError()
        try:
            response = self._egress_for(host).get(url)
        except (EgressRefusedError, EgressFailedError) as exc:
            raise ProviderUnavailableError() from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError()
        try:
            payload = json.loads(response.content)
        except ValueError as exc:
            raise ProviderUnavailableError() from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError()
        return payload

    def discovery(self) -> dict[str, Any]:
        """The provider's discovery document (fetched once, then cached)."""
        with self._lock:
            if self._discovery is None:
                document = self._get_json(
                    self._config.issuer.rstrip("/") + _DISCOVERY_PATH
                )
                # IdP mix-up defense: the document must claim exactly the configured
                # issuer, and must name the three endpoints the code flow needs.
                if document.get("issuer") != self._config.issuer:
                    raise ProviderUnavailableError(
                        "The provider's discovery document does not match the "
                        "configured issuer."
                    )
                for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                    if not document.get(key):
                        raise ProviderUnavailableError(
                            "The provider's discovery document is missing a "
                            "required endpoint."
                        )
                self._discovery = document
            return self._discovery

    def _signing_key(self, token: str) -> jwt.PyJWK:
        """The JWKS key for *token*'s ``kid`` — re-fetching once on rotation."""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise AuthenticationError() from exc
        if not kid:
            raise AuthenticationError()
        jwks_uri = str(self.discovery()["jwks_uri"])
        with self._lock:
            for refreshed in (False, True):
                if self._jwks is None or refreshed:
                    try:
                        self._jwks = jwt.PyJWKSet.from_dict(self._get_json(jwks_uri))
                    except jwt.PyJWTError as exc:
                        raise ProviderUnavailableError() from exc
                for key in self._jwks.keys:
                    if key.key_id == kid:
                        return key
            raise AuthenticationError()

    # ------------------------------------------------------------------ #
    # the code flow
    # ------------------------------------------------------------------ #
    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        """The IdP authorize URL for one flow — code + PKCE (S256) parameters only."""
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "scope": " ".join(self._config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        endpoint = str(self.discovery()["authorization_endpoint"])
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{params}"

    def exchange_code(self, *, code: str, code_verifier: str, client_secret: str) -> str:
        """Redeem *code* at the token endpoint; return the raw ID token.

        The IdP's access / refresh tokens in the response are deliberately ignored
        (ADR 0058): Terp mints its own session, so they are used zero times and never
        stored or returned.
        """
        endpoint = str(self.discovery()["token_endpoint"])
        host = urlsplit(endpoint).hostname
        if not host:
            raise ProviderUnavailableError()
        # Form-encoded by hand because the egress client takes bytes: it carries no
        # opinion about how a body was serialised, which is the right amount of opinion
        # for a transport to have. The content type has to be declared for the same
        # reason — nothing infers it from the argument any more.
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config.redirect_uri,
                "client_id": self._config.client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            }
        ).encode("utf-8")
        try:
            response = self._egress_for(host).post(
                endpoint,
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (EgressRefusedError, EgressFailedError) as exc:
            raise ProviderUnavailableError() from exc
        if response.status_code != 200:
            # A refused exchange (bad / replayed / expired code) is an auth failure, not
            # an outage — the uniform 401.
            raise AuthenticationError()
        try:
            payload = json.loads(response.content)
        except ValueError as exc:
            raise ProviderUnavailableError() from exc
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise AuthenticationError()
        return id_token

    def validate_id_token(self, raw_token: str, *, nonce: str) -> OIDCClaims:
        """Fully validate *raw_token*; return the typed claims or raise the uniform 401."""
        key = self._signing_key(raw_token)
        try:
            payload = jwt.decode(
                raw_token,
                key=key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._config.client_id,
                issuer=self._config.issuer,
                leeway=CLOCK_SKEW_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError() from exc
        if payload.get("nonce") != nonce:
            # The nonce binds the token to the flow this server started; a mismatch
            # is an injected / replayed token.
            raise AuthenticationError()
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError()
        email = payload.get("email")
        return OIDCClaims(
            issuer=self._config.issuer,
            subject=subject,
            email=email if isinstance(email, str) and email else None,
            email_verified=payload.get("email_verified") is True,
            name=payload.get("name") if isinstance(payload.get("name"), str) else None,
            raw=payload,
        )


__all__ = [
    "ALLOWED_ALGORITHMS",
    "CLOCK_SKEW_LEEWAY_SECONDS",
    "MAX_RESPONSE_BYTES",
    "OIDCClient",
    "ProviderUnavailableError",
]
