"""Federated identity (ADR 0058): the identity-side backing for SSO logins.

Covers the link/resolve/JIT-provision service, the ``(issuer, subject)``-only
resolution rule (never email matching), the SSO-only nullable-password user shape
(and the ``authenticate`` refusal it implies), and the example app's wired
``resolve_or_provision`` seam end to end against the persisted store.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, select

from terp.core import Roles
from terp.core.config import settings

from terp.capabilities.identity import (
    FederatedIdentity,
    FederatedIdentityService,
    IdentityService,
    User,
)

_ISSUER = "https://idp.example.test"
_PASSWORD = "correct horse battery staple"  # noqa: S105 - test fixture


def _make_sso_user(session: Session, email: str = "sso@acme.test") -> User:
    """Persist an SSO-only user (no local password) directly for a test."""
    user = User(email=email, hashed_password=None, role=int(Roles.VIEWER))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# linking + resolution — (issuer, subject) only, never email
# --------------------------------------------------------------------------- #
def test_link_then_resolve_returns_the_linked_active_user(db_session: Session) -> None:
    service = FederatedIdentityService()
    user = _make_sso_user(db_session)
    service.link(db_session, user_id=user.id, issuer=_ISSUER, subject="sub-1")

    resolved = service.resolve_or_provision(
        db_session, issuer=_ISSUER, subject="sub-1", email=None, email_verified=False
    )

    assert resolved is not None and resolved.id == user.id


def test_resolution_never_matches_by_email(db_session: Session, make_user) -> None:
    # A local user exists with exactly the email the IdP asserts — but with no link,
    # resolution refuses (matching by email is the account-takeover vector ADR 0058
    # names), even with provisioning enabled and the email verified.
    make_user("victim@acme.test", _PASSWORD)
    service = FederatedIdentityService(allow_provisioning=True)

    resolved = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="attacker-subject",
        email="victim@acme.test",
        email_verified=True,
    )

    assert resolved is None
    assert (
        db_session.exec(select(FederatedIdentity)).first() is None
    )  # and no link row appeared


def test_a_deactivated_linked_user_is_refused(db_session: Session) -> None:
    service = FederatedIdentityService()
    user = _make_sso_user(db_session)
    service.link(db_session, user_id=user.id, issuer=_ISSUER, subject="sub-1")
    user.is_active = False
    db_session.add(user)
    db_session.commit()

    assert (
        service.resolve_or_provision(
            db_session, issuer=_ISSUER, subject="sub-1", email=None, email_verified=False
        )
        is None
    )


def test_a_link_whose_user_row_vanished_is_refused(db_session: Session) -> None:
    service = FederatedIdentityService()
    service.link(db_session, user_id=uuid.uuid4(), issuer=_ISSUER, subject="ghost")
    assert (
        service.resolve_or_provision(
            db_session, issuer=_ISSUER, subject="ghost", email=None, email_verified=False
        )
        is None
    )


def test_one_external_identity_cannot_link_to_two_users(db_session: Session) -> None:
    from terp.core import ConflictError

    service = FederatedIdentityService()
    first = _make_sso_user(db_session, "one@acme.test")
    second = _make_sso_user(db_session, "two@acme.test")
    service.link(db_session, user_id=first.id, issuer=_ISSUER, subject="sub-1")
    with pytest.raises(ConflictError):
        service.link(db_session, user_id=second.id, issuer=_ISSUER, subject="sub-1")


# --------------------------------------------------------------------------- #
# JIT provisioning — off by default, verified email only, lowest rank
# --------------------------------------------------------------------------- #
def test_provisioning_is_off_by_default(db_session: Session) -> None:
    assert (
        FederatedIdentityService().resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="new-sub",
            email="new@acme.test",
            email_verified=True,
        )
        is None
    )


def test_provisioning_requires_a_verified_email(db_session: Session) -> None:
    service = FederatedIdentityService(allow_provisioning=True)
    for email, verified in ((None, True), ("new@acme.test", False)):
        assert (
            service.resolve_or_provision(
                db_session,
                issuer=_ISSUER,
                subject="new-sub",
                email=email,
                email_verified=verified,
            )
            is None
        )


def test_provisioning_creates_a_linked_sso_only_viewer(db_session: Session) -> None:
    service = FederatedIdentityService(allow_provisioning=True)

    user = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="new-sub",
        email="new@acme.test",
        email_verified=True,
    )

    assert user is not None
    assert user.hashed_password is None  # SSO-only: no local credential
    assert user.role == int(Roles.VIEWER)  # lowest default rank
    # the link row was created in the same audited flow, so the next login resolves it
    again = service.resolve_or_provision(
        db_session, issuer=_ISSUER, subject="new-sub", email=None, email_verified=False
    )
    assert again is not None and again.id == user.id


def test_provisioning_can_target_a_custom_rank(db_session: Session) -> None:
    service = FederatedIdentityService(allow_provisioning=True, provisioned_rank=int(Roles.EDITOR))
    user = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="e-sub",
        email="e@acme.test",
        email_verified=True,
    )
    assert user is not None and user.role == int(Roles.EDITOR)


def test_provisioning_lands_active_by_default(db_session: Session) -> None:
    """The default is unchanged, and pinned: a flipped default is a silent lockout."""
    service = FederatedIdentityService(allow_provisioning=True)
    user = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="a-sub",
        email="a@acme.test",
        email_verified=True,
    )
    assert user is not None and user.is_active is True


def test_a_pending_account_is_written_and_the_login_still_refused(
    db_session: Session,
) -> None:
    """``provisioned_active=False``: the rows record the request, entry is not granted."""
    service = FederatedIdentityService(allow_provisioning=True, provisioned_active=False)

    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="p-sub",
            email="pending@acme.test",
            email_verified=True,
        )
        is None
    )

    stored = db_session.exec(select(User).where(User.email == "pending@acme.test")).first()
    assert stored is not None and stored.is_active is False
    assert service.get_link(db_session, _ISSUER, "p-sub") is not None


def test_a_pending_account_is_admitted_only_once_activated(db_session: Session) -> None:
    """Both sides of the guard: refused while inactive, resolved after activation."""
    service = FederatedIdentityService(allow_provisioning=True, provisioned_active=False)
    service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="p2-sub",
        email="pending2@acme.test",
        email_verified=True,
    )

    # A second attempt takes the *linked* path and is refused there — no duplicate row,
    # and no admission the first refusal was supposed to withhold.
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="p2-sub",
            email="pending2@acme.test",
            email_verified=True,
        )
        is None
    )
    assert len(db_session.exec(select(User).where(User.email == "pending2@acme.test")).all()) == 1

    stored = db_session.exec(select(User).where(User.email == "pending2@acme.test")).first()
    assert stored is not None
    stored.is_active = True
    db_session.add(stored)
    db_session.commit()

    admitted = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="p2-sub",
        email="pending2@acme.test",
        email_verified=True,
    )
    assert admitted is not None and admitted.id == stored.id


# --------------------------------------------------------------------------- #
# identity service — SSO-only users and the federated principal resolver
# --------------------------------------------------------------------------- #
def test_password_login_refuses_an_sso_only_user(db_session: Session) -> None:
    user = _make_sso_user(db_session)
    identity = IdentityService()
    assert identity.authenticate(db_session, user.email, "anything") is None
    assert identity.authenticate(db_session, user.email, "") is None


def test_principal_for_federated_resolves_only_a_linked_active_user(
    db_session: Session,
) -> None:
    identity = IdentityService()
    assert identity.principal_for_federated(db_session, _ISSUER, "nobody") is None

    user = _make_sso_user(db_session)
    FederatedIdentityService().link(
        db_session, user_id=user.id, issuer=_ISSUER, subject="sub-1"
    )
    principal = identity.principal_for_federated(db_session, _ISSUER, "sub-1")
    assert principal is not None and principal.id == user.id

    user.is_active = False
    db_session.add(user)
    db_session.commit()
    assert identity.principal_for_federated(db_session, _ISSUER, "sub-1") is None


def test_principal_for_user_resolves_the_stored_rank(db_session: Session) -> None:
    user = _make_sso_user(db_session)
    principal = IdentityService().principal_for_user(db_session, user)
    assert principal.id == user.id
    assert principal.role.rank == int(Roles.VIEWER)


# --------------------------------------------------------------------------- #
# the example app's wired seam (dogfooding the composition)
# --------------------------------------------------------------------------- #
def test_example_resolver_provisions_then_resolves(db_session: Session) -> None:
    from terp.capabilities.oidc import OIDCClaims

    from app.auth import _resolve_sso_principal

    claims = OIDCClaims(
        issuer="http://localhost:5556/dex",
        subject="dex-sub-1",
        email="dexuser@acme.test",
        email_verified=True,
    )
    principal = _resolve_sso_principal(db_session, claims)
    assert principal is not None  # JIT-provisioned on first SSO login

    unverified = OIDCClaims(issuer=claims.issuer, subject="other", email="x@acme.test")
    assert _resolve_sso_principal(db_session, unverified) is None


# --------------------------------------------------------------------------- #
# whose identities may be provisioned (the allowlist seam)
# --------------------------------------------------------------------------- #
def test_a_domain_allowlist_refuses_a_verified_stranger(db_session: Session) -> None:
    """Verified-email checks the claim, not who may hold one.

    Against a multi-tenant IdP — an app registration left open to any directory — a
    perfectly genuine, perfectly verified account from a directory this deployment has
    never heard of clears every other gate here. That is open registration, and the
    only thing that closes it is a statement about which identities are accepted.
    """
    service = FederatedIdentityService(
        allow_provisioning=True, allowed_email_domains=("acme.test",)
    )
    outsider = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="stranger",
        email="attacker@evil.test",
        email_verified=True,
    )
    assert outsider is None
    # And nothing was written on the way to refusing.
    assert db_session.exec(select(User).where(User.email == "attacker@evil.test")).first() is None

    insider = service.resolve_or_provision(
        db_session,
        issuer=_ISSUER,
        subject="colleague",
        email="new.person@ACME.test",  # the match is case-insensitive
        email_verified=True,
    )
    assert insider is not None


def test_a_subdomain_of_an_allowed_domain_is_not_allowed(db_session: Session) -> None:
    """Exact match, never a suffix.

    Accepting every subdomain hands provisioning to whoever controls one, and a
    deployment that genuinely wants ``sub.acme.test`` can say so in one more entry.
    """
    service = FederatedIdentityService(
        allow_provisioning=True, allowed_email_domains=("acme.test",)
    )
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="sub",
            email="someone@evil.acme.test",
            email_verified=True,
        )
        is None
    )


def test_a_provision_gate_decides_per_claim(db_session: Session) -> None:
    """The richer half: a rule that is not a list of domains still gets to be the rule."""
    invited = {"expected@acme.test"}
    service = FederatedIdentityService(
        allow_provisioning=True, provision_allowed=lambda email: email in invited
    )
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="uninvited",
            email="walk-in@acme.test",
            email_verified=True,
        )
        is None
    )
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="invited",
            email="expected@acme.test",
            email_verified=True,
        )
        is not None
    )


def test_both_gates_apply_and_either_can_refuse(db_session: Session) -> None:
    """A gate that could widen an allowlist would not be an allowlist.

    Asserted on the combination because that is where the AND could silently become an
    OR: the callback says yes to an address the domain list refuses.
    """
    service = FederatedIdentityService(
        allow_provisioning=True,
        allowed_email_domains=("acme.test",),
        provision_allowed=lambda _email: True,
    )
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="widened",
            email="anyone@evil.test",
            email_verified=True,
        )
        is None
    )


def test_an_empty_allowlist_is_refused_at_construction() -> None:
    """An empty tuple reads as "allow nothing" and behaves as "declined to say"."""
    with pytest.raises(ValueError, match="at least one non-empty domain"):
        FederatedIdentityService(allow_provisioning=True, allowed_email_domains=())
    with pytest.raises(ValueError, match="at least one non-empty domain"):
        FederatedIdentityService(allow_provisioning=True, allowed_email_domains=("  ",))


def test_production_refuses_provisioning_with_no_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed at construction, not at the first stranger's login."""
    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    with pytest.raises(ValueError, match="requires an identity allowlist in production"):
        FederatedIdentityService(allow_provisioning=True)
    # Either gate satisfies it; provisioning-off never needed one.
    FederatedIdentityService(allow_provisioning=True, allowed_email_domains=("acme.test",))
    FederatedIdentityService(allow_provisioning=True, provision_allowed=lambda _e: True)
    FederatedIdentityService()


def test_development_still_provisions_without_an_allowlist(db_session: Session) -> None:
    """A local run against a test IdP needs no ceremony — the refusal is production's."""
    service = FederatedIdentityService(allow_provisioning=True)
    assert (
        service.resolve_or_provision(
            db_session,
            issuer=_ISSUER,
            subject="dev-sub",
            email="dev@anywhere.test",
            email_verified=True,
        )
        is not None
    )
