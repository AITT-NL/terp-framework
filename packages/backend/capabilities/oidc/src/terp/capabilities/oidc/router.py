"""The SSO login router + ``ModuleSpec`` builder for the OIDC capability (ADR 0058).

Two public routes per configured provider, shaped for a SPA client:

* ``GET /{provider}/authorize`` opens a flow — generates ``state`` / ``nonce`` / PKCE
  verifier into the single-use state store and returns the IdP authorize URL; and
* ``POST /{provider}/callback`` finishes it — consumes the state (single-use,
  expiring), exchanges the code (PKCE verifier + client secret), fully validates the
  ID token, resolves a principal through the app-wired identity seam, and mints a
  normal **Terp** session (the IdP's tokens are used once and discarded).

The capability owns protocol, never users: ``resolve_or_provision(session, claims)``
is the one identity seam (the ``authenticate`` analog), app-wired to the identity
capability's federated store. Token minting reuses the auth capability's machinery
unchanged — the ``tenant_resolver`` / ``token_version_resolver`` (ADR 0031) /
``refresh_issuer`` (ADR 0054) seams — so revocation, ``/refresh``, ``/me``, and
``/logout`` cover an SSO session exactly as a password one.

A sealed (``enc:v1:``) client secret requires the app-wired ``secret_resolver`` (the
app's single allowlisted decrypt site, ADR 0055); a sealed secret with no resolver is
refused at construction, and the capability itself never calls ``decrypt_config``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx
from fastapi import APIRouter, Request, Response
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    ModuleSpec,
    NotFoundError,
    Policy,
    Principal,
    SessionDep,
    client_ip,
    is_sealed_config,
)

from terp.capabilities.auth import (
    AccessToken,
    LoginTenantResolver,
    LoginThrottle,
    RefreshIssuer,
    TokenVersionResolver,
    create_access_token,
    set_refresh_cookie,
)

from terp.capabilities.oidc.client import OIDCClient
from terp.capabilities.oidc.config import OIDCClaims, OIDCProviderConfig
from terp.capabilities.oidc.schemas import AuthorizationRequest, OIDCCallbackRequest
from terp.capabilities.oidc.state import (
    InMemoryStateStore,
    OIDCStateStore,
    code_challenge_s256,
)

# The one identity seam (the ``authenticate`` analog): validated claims in, a
# principal (or a refusal) out. App-wired so OIDC never imports where users live.
IdentityResolver = Callable[[Session, OIDCClaims], Principal | None]
# Unseal a sealed client secret — app-wired to its single allowlisted decrypt site
# (ADR 0055); the capability never decrypts.
SecretResolver = Callable[[str], str]


def _throttle_key(provider: str, request: Request) -> str:
    """Per-source lockout key for the callback (the login-throttle analog).

    Keys on the centrally resolved client address (``terp.core.client_ip``), so a
    deployment that declared ``SecurityConfig.trusted_proxy_hops`` throttles the
    real caller rather than collapsing everyone onto the proxy's IP.
    """
    return f"oidc:{provider}:{client_ip(request)}"


def build_oidc_router(
    providers: Sequence[OIDCProviderConfig],
    resolve_or_provision: IdentityResolver,
    *,
    tenant_resolver: LoginTenantResolver | None = None,
    token_version_resolver: TokenVersionResolver | None = None,
    refresh_issuer: RefreshIssuer | None = None,
    throttle: LoginThrottle | None = None,
    state_store: OIDCStateStore | None = None,
    secret_resolver: SecretResolver | None = None,
    http_factory: Callable[[], httpx.Client] | None = None,
) -> APIRouter:
    """Build the per-provider ``/authorize`` + ``/callback`` router (fail-fast).

    Construction refuses an empty or name-colliding registry, and a sealed client
    secret with no *secret_resolver* — a misconfigured provider fails the boot, not
    the first login.
    """
    if not providers:
        raise ValueError("build_oidc_router requires at least one OIDCProviderConfig")
    registry: dict[str, OIDCProviderConfig] = {}
    for config in providers:
        if config.name in registry:
            raise ValueError(f"duplicate OIDC provider name {config.name!r}")
        if is_sealed_config(config.client_secret) and secret_resolver is None:
            raise ValueError(
                f"OIDC provider {config.name!r} has a sealed client_secret but no "
                "secret_resolver is wired; the capability never decrypts (ADR 0055)"
            )
        registry[config.name] = config

    clients = {
        name: OIDCClient(config, http_factory=http_factory)
        for name, config in registry.items()
    }
    store = state_store if state_store is not None else InMemoryStateStore()
    active_throttle = throttle if throttle is not None else LoginThrottle()

    def _client(provider: str) -> OIDCClient:
        client = clients.get(provider)
        if client is None:
            raise NotFoundError(f"Unknown SSO provider {provider!r}.")
        return client

    def _client_secret(config: OIDCProviderConfig) -> str:
        if is_sealed_config(config.client_secret):
            assert secret_resolver is not None  # noqa: S101 - enforced at construction
            return secret_resolver(config.client_secret)
        return config.client_secret

    def _mint_access_token(session: Session, principal: Principal) -> str:
        tenant = tenant_resolver(session, principal) if tenant_resolver is not None else None
        token_version = (
            token_version_resolver(session, principal)
            if token_version_resolver is not None
            else 0
        )
        return create_access_token(
            subject=principal.id,
            role=principal.role,
            tenant=tenant,
            token_version=token_version,
        )

    router = APIRouter(tags=["auth"])

    @router.get("/{provider}/authorize", response_model=AuthorizationRequest)
    def authorize(provider: str) -> AuthorizationRequest:
        client = _client(provider)
        state, pending = store.issue(provider)
        return AuthorizationRequest(
            provider=provider,
            authorization_url=client.authorization_url(
                state=state,
                nonce=pending.nonce,
                code_challenge=code_challenge_s256(pending.code_verifier),
            ),
        )

    @router.post("/{provider}/callback", response_model=AccessToken)
    def callback(
        provider: str,
        payload: OIDCCallbackRequest,
        session: SessionDep,
        request: Request,
        response: Response,
    ) -> AccessToken:
        client = _client(provider)
        identifier = _throttle_key(provider, request)
        active_throttle.check(identifier)
        pending = store.consume(payload.state, provider)
        if pending is None:
            # Unknown, expired, replayed, or cross-provider state — the uniform 401.
            active_throttle.record_failure(identifier)
            raise AuthenticationError()
        id_token = client.exchange_code(
            code=payload.code,
            code_verifier=pending.code_verifier,
            client_secret=_client_secret(client.config),
        )
        claims = client.validate_id_token(id_token, nonce=pending.nonce)
        principal = resolve_or_provision(session, claims)
        if principal is None:
            active_throttle.record_failure(identifier)
            raise AuthenticationError()
        active_throttle.record_success(identifier)
        token = _mint_access_token(session, principal)
        if refresh_issuer is not None:
            # The SSO session gets the same rotating refresh cookie a password login
            # does (ADR 0054), so reloads and /refresh work identically.
            set_refresh_cookie(response, refresh_issuer(session, principal.id))
        return AccessToken(access_token=token)

    return router


def build_oidc_module(
    providers: Sequence[OIDCProviderConfig],
    resolve_or_provision: IdentityResolver,
    *,
    name: str = "oidc",
    tenant_resolver: LoginTenantResolver | None = None,
    token_version_resolver: TokenVersionResolver | None = None,
    refresh_issuer: RefreshIssuer | None = None,
    throttle: LoginThrottle | None = None,
    state_store: OIDCStateStore | None = None,
    secret_resolver: SecretResolver | None = None,
    http_factory: Callable[[], httpx.Client] | None = None,
) -> ModuleSpec:
    """Build the SSO ``ModuleSpec`` (public authorize + callback endpoints)."""
    return ModuleSpec(
        name=name,
        router=build_oidc_router(
            providers,
            resolve_or_provision,
            tenant_resolver=tenant_resolver,
            token_version_resolver=token_version_resolver,
            refresh_issuer=refresh_issuer,
            throttle=throttle,
            state_store=state_store,
            secret_resolver=secret_resolver,
            http_factory=http_factory,
        ),
        policy=Policy.public_write(
            reason="SSO login endpoints must be reachable without a token"
        ),
    )


__all__ = [
    "IdentityResolver",
    "SecretResolver",
    "build_oidc_module",
    "build_oidc_router",
]
