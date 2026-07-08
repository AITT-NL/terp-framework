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

The outbound HTTP client lives only inside this capability (like the webhooks delivery
client); tests inject an ``http_factory`` returning an ``httpx.Client`` over a mock
transport.
"""

from __future__ import annotations

from threading import Lock
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from terp.core import AppError, AuthenticationError

from terp.capabilities.oidc.config import OIDCClaims, OIDCProviderConfig

#: Asymmetric signature algorithms accepted on an ID token. ``alg=none`` and the
#: HS* (symmetric) family are excluded by construction: with HS* the "key" would be
#: the client secret, and a leaked secret could then forge identities.
ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256", "RS384", "RS512", "PS256", "ES256", "ES384")

#: Bounded clock skew for ``exp`` / ``iat`` validation, in seconds.
CLOCK_SKEW_LEEWAY_SECONDS = 60

_DISCOVERY_PATH = "/.well-known/openid-configuration"
_HTTP_TIMEOUT_SECONDS = 10.0


class ProviderUnavailableError(AppError):
    """502 — the identity provider could not be reached or answered malformed data."""

    status_code = 502
    code = "oidc_provider_unavailable"
    default_message = "The identity provider is unavailable; please try again."


def _default_http_factory() -> httpx.Client:
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


class OIDCClient:
    """The protocol client for one configured provider."""

    def __init__(
        self,
        config: OIDCProviderConfig,
        *,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._config = config
        self._http_factory = http_factory or _default_http_factory
        self._lock = Lock()
        self._discovery: dict[str, Any] | None = None
        self._jwks: jwt.PyJWKSet | None = None

    @property
    def config(self) -> OIDCProviderConfig:
        return self._config

    # ------------------------------------------------------------------ #
    # discovery + JWKS
    # ------------------------------------------------------------------ #
    def _get_json(self, url: str) -> dict[str, Any]:
        """GET *url* and parse JSON; any transport / status / parse failure is a 502."""
        try:
            with self._http_factory() as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
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
        params = httpx.QueryParams(
            response_type="code",
            client_id=self._config.client_id,
            redirect_uri=self._config.redirect_uri,
            scope=" ".join(self._config.scopes),
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method="S256",
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
        try:
            with self._http_factory() as client:
                response = client.post(
                    endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self._config.redirect_uri,
                        "client_id": self._config.client_id,
                        "client_secret": client_secret,
                        "code_verifier": code_verifier,
                    },
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError() from exc
        if response.status_code != 200:
            # A refused exchange (bad / replayed / expired code) is an auth failure,
            # not an outage — the uniform 401.
            raise AuthenticationError()
        try:
            payload = response.json()
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
    "OIDCClient",
    "ProviderUnavailableError",
]
