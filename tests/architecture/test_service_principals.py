"""Service-principal credentials (ADR 0088): the machine subject end to end.

The feature exists to remove a specific temptation: with no machine credential, an
integration has to log in as a person, and the person it picks is an admin. These
tests pin the properties that make the sanctioned path trustworthy enough to take —
that a machine token is *distinguishable*, *revocable*, *expiring*, and authorized by
exactly the same guard as everyone else.
"""

from __future__ import annotations

import datetime
import uuid

import jwt
import pytest
from sqlmodel import Session, SQLModel, create_engine

from terp.core import AuthenticationError, Roles
from terp.core.config import settings

from terp.capabilities.auth import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    SubjectKind,
    build_login_router,
    create_access_token,
    decode_access_token,
)
from terp.capabilities.identity import IdentityService, ServiceAccountService
from terp.capabilities.identity.schemas import ServiceAccountCreate

_KEY = "terp-service-principal-secret-key-0123456789"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _KEY)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", ())


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _provision(
    service: ServiceAccountService,
    session: Session,
    *,
    expires_at: datetime.datetime | None = None,
):
    return service.provision(
        session,
        ServiceAccountCreate(
            name="nightly-sync", role_rank=int(Roles.EDITOR), expires_at=expires_at
        ),
    )


# --------------------------------------------------------------------------- #
# The signed subject kind
# --------------------------------------------------------------------------- #
def test_a_machine_token_says_it_is_a_machine() -> None:
    token = create_access_token(
        subject=uuid.uuid4(), role=Roles.EDITOR, kind=SubjectKind.SERVICE
    )
    assert decode_access_token(token).kind is SubjectKind.SERVICE


def test_a_token_minted_before_the_kind_claim_reads_as_a_user() -> None:
    # A token in flight across the deploy that introduced ADR 0088 has no `kind`. It
    # must keep working as what it always was, or a rollout logs everyone out.
    now = datetime.datetime.now(datetime.UTC)
    legacy = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "rank": int(Roles.ADMIN),
            "tv": 0,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
        },
        _KEY,
        algorithm="HS256",
    )
    assert decode_access_token(legacy).kind is SubjectKind.USER


def test_an_unknown_kind_is_refused_not_downgraded() -> None:
    # Fail closed: a kind this build does not understand must not fall back to the
    # subject type with the broadest reach.
    now = datetime.datetime.now(datetime.UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "rank": int(Roles.ADMIN),
            "tv": 0,
            "kind": "robot",
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
        },
        _KEY,
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


# --------------------------------------------------------------------------- #
# Client-credentials authentication
# --------------------------------------------------------------------------- #
def test_the_secret_is_returned_once_and_never_stored_in_the_clear(
    session: Session,
) -> None:
    account, secret = _provision(ServiceAccountService(), session)
    assert secret
    assert account.hashed_secret != secret
    assert secret not in account.hashed_secret


def test_a_provisioned_account_authenticates_at_its_declared_rank(
    session: Session,
) -> None:
    service = ServiceAccountService()
    account, secret = _provision(service, session)

    principal = service.authenticate_client(session, account.client_id, secret)

    assert principal is not None
    assert principal.id == account.id
    assert principal.kind == SubjectKind.SERVICE
    assert principal.role.rank == int(Roles.EDITOR)


def test_a_wrong_secret_and_an_unknown_client_both_fail(session: Session) -> None:
    service = ServiceAccountService()
    account, _secret = _provision(service, session)

    assert service.authenticate_client(session, account.client_id, "wrong") is None
    assert service.authenticate_client(session, "no-such-client", "wrong") is None


def test_an_expired_account_cannot_authenticate(session: Session) -> None:
    service = ServiceAccountService()
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    account, secret = _provision(service, session, expires_at=past)

    assert service.authenticate_client(session, account.client_id, secret) is None


def test_authenticating_records_that_the_integration_is_still_alive(
    session: Session,
) -> None:
    service = ServiceAccountService()
    account, secret = _provision(service, session)
    assert account.last_used_at is None

    service.authenticate_client(session, account.client_id, secret)

    assert account.last_used_at is not None


# --------------------------------------------------------------------------- #
# Revocation — the reason a machine credential is safe to hand out
# --------------------------------------------------------------------------- #
def test_revoking_kills_outstanding_machine_tokens_at_once(session: Session) -> None:
    service = ServiceAccountService()
    identity = IdentityService(service_accounts=service)
    account, secret = _provision(service, session)
    principal = service.authenticate_client(session, account.client_id, secret)
    assert principal is not None
    claims = decode_access_token(
        create_access_token(
            subject=principal.id,
            role=principal.role,
            token_version=service.token_version_for(session, principal),
            kind=SubjectKind.SERVICE,
        )
    )
    assert identity.token_is_current(session, claims)

    assert service.revoke(session, account.id)

    assert not identity.token_is_current(session, claims)


def test_an_account_that_lapses_mid_token_stops_working(session: Session) -> None:
    service = ServiceAccountService()
    identity = IdentityService(service_accounts=service)
    soon = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    account, secret = _provision(service, session, expires_at=soon)
    principal = service.authenticate_client(session, account.client_id, secret)
    assert principal is not None
    claims = decode_access_token(
        create_access_token(
            subject=principal.id, role=principal.role, kind=SubjectKind.SERVICE
        )
    )

    account.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    assert not identity.token_is_current(session, claims)


def test_a_machine_token_is_not_validated_against_the_user_table(
    session: Session,
) -> None:
    # The signed kind decides which store answers. A service subject id must never be
    # looked up as a user (and vice versa) — otherwise a subject present in both
    # tables would resolve by lookup order rather than by what the credential is.
    service = ServiceAccountService()
    identity = IdentityService(service_accounts=service)
    account, secret = _provision(service, session)
    principal = service.authenticate_client(session, account.client_id, secret)
    assert principal is not None

    as_user = decode_access_token(
        create_access_token(
            subject=principal.id, role=principal.role, kind=SubjectKind.USER
        )
    )
    assert not identity.token_is_current(session, as_user)


# --------------------------------------------------------------------------- #
# Wiring — the fail-closed construction guards
# --------------------------------------------------------------------------- #
def _authenticate(session, email, password):  # pragma: no cover - never called
    return None


def test_the_token_route_is_mounted_only_when_the_seams_are_wired() -> None:
    bare = build_login_router(_authenticate)
    assert "/token" not in {route.path for route in bare.routes}

    wired = build_login_router(
        _authenticate,
        authenticate_client=lambda session, cid, secret: None,
        service_token_version_resolver=lambda session, principal: 0,
    )
    assert "/token" in {route.path for route in wired.routes}


def test_half_wired_client_credentials_are_refused_at_construction() -> None:
    # Minting a machine token without the account's current epoch signs it stale: the
    # credential works exactly once, in the mint response, and fails forever after.
    with pytest.raises(ValueError, match="half-wired"):
        build_login_router(
            _authenticate, authenticate_client=lambda session, cid, secret: None
        )
    with pytest.raises(ValueError, match="half-wired"):
        build_login_router(
            _authenticate, service_token_version_resolver=lambda session, p: 0
        )
