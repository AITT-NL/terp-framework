"""Coverage gate: capability fail-closed / branch paths not hit end-to-end."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import jwt
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from terp.core import AuthenticationError, Principal, Role, Roles
from terp.core.config import settings

from terp.capabilities.auth import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    create_access_token,
    decode_access_token,
    get_principal,
    tenant_from_bearer,
)
from terp.capabilities.auth.deps import _bearer_token
from terp.capabilities.tenancy import TenantMiddleware

_KEY = "terp-coverage-test-secret-key-0123456789ab"


def _request(headers: dict[str, str] | None = None) -> Request:
    # ASGI requires lowercase header names in the raw scope.
    raw = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "headers": raw})


# --------------------------------------------------------------------------- #
# auth: tokens + bearer extraction
# --------------------------------------------------------------------------- #
def test_bearer_token_extraction() -> None:
    assert _bearer_token(_request()) is None
    assert _bearer_token(_request({"Authorization": "Basic abc"})) is None
    assert _bearer_token(_request({"Authorization": "Bearer abc"})) == "abc"


def test_decode_rejects_garbage_and_malformed_payload() -> None:
    settings.SECRET_KEY = _KEY
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.jwt")
    malformed = jwt.encode({"foo": "bar"}, _KEY, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(malformed)


def test_custom_role_round_trips_through_the_jwt() -> None:
    # Genericness proof: a consumer-defined role (not viewer/editor/admin) keeps
    # its name and rank across issue -> decode, with no coercion to a fixed tier.
    settings.SECRET_KEY = _KEY
    approver = Role("approver", rank=25)
    claims = decode_access_token(create_access_token(subject=uuid.uuid4(), role=approver))
    assert claims.role == approver


def test_tokens_sign_and_require_the_registered_audience_and_issuer() -> None:
    # ADR 0076: every access token carries the fixed iss/aud pair, and decode
    # refuses a token minted without them or for a foreign audience/issuer —
    # even one signed with the very same shared secret.
    settings.SECRET_KEY = _KEY
    raw = jwt.decode(
        create_access_token(subject=uuid.uuid4(), role=Roles.EDITOR),
        _KEY,
        algorithms=["HS256"],
        audience=TOKEN_AUDIENCE,
        issuer=TOKEN_ISSUER,
    )
    assert raw["iss"] == TOKEN_ISSUER
    assert raw["aud"] == TOKEN_AUDIENCE

    now = datetime.datetime.now(datetime.UTC)
    base: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "role": "editor",
        "rank": 20,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    for tampered in (
        {**base, "aud": "some-other-service"},
        {**base, "iss": "some-other-issuer"},
        {key: value for key, value in base.items() if key != "aud"},
        {key: value for key, value in base.items() if key != "iss"},
    ):
        foreign = jwt.encode(tampered, _KEY, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            decode_access_token(foreign)
    # A verified envelope with a malformed payload still refuses (fail closed).
    with pytest.raises(AuthenticationError):
        decode_access_token(jwt.encode({**base, "sub": "not-a-uuid"}, _KEY, algorithm="HS256"))


def test_rotation_fallback_verifies_old_tokens_but_never_signs_new_ones() -> None:
    # ADR 0076: SECRET_KEY_FALLBACKS keeps an already-issued token valid across a
    # key rotation; signing always uses the current key, and dropping the fallback
    # ends the window fail-closed.
    old_key = "terp-coverage-old-signing-key-0123456789abcd"
    new_key = "terp-coverage-new-signing-key-0123456789abcd"
    settings.SECRET_KEY = old_key
    holder = uuid.uuid4()
    outstanding = create_access_token(subject=holder, role=Roles.EDITOR)
    try:
        settings.SECRET_KEY = new_key
        settings.SECRET_KEY_FALLBACKS = [old_key]
        assert decode_access_token(outstanding).subject == holder
        # A freshly minted token is signed with the *current* key, never a fallback.
        fresh = create_access_token(subject=uuid.uuid4(), role=Roles.EDITOR)
        jwt.decode(
            fresh,
            new_key,
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
        )
        # An expired / tampered token is final — never retried against a fallback.
        expired = create_access_token(
            subject=uuid.uuid4(),
            role=Roles.EDITOR,
            expires_in=datetime.timedelta(minutes=-1),
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(expired)
        # Dropping the fallback closes the window: the old-key token dies.
        settings.SECRET_KEY_FALLBACKS = []
        with pytest.raises(AuthenticationError):
            decode_access_token(outstanding)
    finally:
        settings.SECRET_KEY_FALLBACKS = []
        settings.SECRET_KEY = _KEY


def test_get_principal_and_tenant_from_bearer_round_trip() -> None:
    settings.SECRET_KEY = _KEY
    subject = uuid.uuid4()
    tenant = uuid.uuid4()
    token = create_access_token(subject=subject, role=Roles.EDITOR, tenant=tenant)
    request = _request({"Authorization": f"Bearer {token}"})

    assert get_principal(request) == Principal(id=subject, role=Roles.EDITOR)
    assert tenant_from_bearer(request) == tenant

    # No token → unauthenticated / no tenant.
    assert get_principal(_request()) is None
    assert tenant_from_bearer(_request()) is None

    # Invalid token → fail closed (covers the except branches).
    bad = _request({"Authorization": "Bearer not.a.jwt"})
    assert get_principal(bad) is None
    assert tenant_from_bearer(bad) is None


# --------------------------------------------------------------------------- #
# tenancy: non-HTTP scopes pass straight through
# --------------------------------------------------------------------------- #
def test_tenant_middleware_passes_through_non_http_scope() -> None:
    seen: dict[str, str] = {}

    async def downstream(scope, receive, send) -> None:
        seen["type"] = scope["type"]

    middleware = TenantMiddleware(downstream, resolve_tenant=lambda request: None)
    asyncio.run(middleware({"type": "lifespan"}, None, None))
    assert seen["type"] == "lifespan"


# --------------------------------------------------------------------------- #
# users: the get-by-id route body
# --------------------------------------------------------------------------- #
def test_users_get_user_route_returns_dto() -> None:
    import terp.capabilities.identity.models  # noqa: F401  (register the shared User table)
    from terp.capabilities.users import UserProvision, UsersService
    from terp.capabilities.users.router import get_user

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            created = UsersService().create(
                session,
                UserProvision(email="cover@example.com", password="correct horse battery", role=Roles.VIEWER),
            )
            dto = get_user(created.id, session)
            assert dto.email == "cover@example.com"
    finally:
        engine.dispose()
