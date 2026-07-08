"""``UsersService`` admin-provisioning primitives — idempotent ``ensure_user`` + ``get_by_email``.

These back the bootstrap / seed paths (``terp user create`` / ``terp seed``): the create-if-absent
logic lives once on the service, so the CLI and every app's seed share one audited primitive
instead of re-implementing the lookup.
"""

from __future__ import annotations

from sqlmodel import Session

from terp.core import Roles

from terp.capabilities.users import UserProvision, UsersService

_PASSWORD = "correct horse battery staple"  # noqa: S105 - test fixture, satisfies the policy


def test_get_by_email_returns_none_when_absent(db_session: Session) -> None:
    assert UsersService().get_by_email(db_session, "ghost@acme.test") is None


def test_ensure_user_creates_when_absent(db_session: Session) -> None:
    service = UsersService()
    user = service.ensure_user(
        db_session,
        UserProvision(email="ensure@acme.test", password=_PASSWORD, role=int(Roles.ADMIN)),
    )
    assert user.id is not None
    assert service.get_by_email(db_session, "ensure@acme.test") is not None


def test_ensure_user_is_idempotent_and_leaves_the_existing_row_untouched(
    db_session: Session,
) -> None:
    service = UsersService()
    created = service.ensure_user(
        db_session,
        UserProvision(email="dup@acme.test", password=_PASSWORD, role=int(Roles.ADMIN)),
    )
    # A second call for the same email returns the existing user without re-creating or
    # demoting it (the seed-re-run safety property).
    again = service.ensure_user(
        db_session,
        UserProvision(email="dup@acme.test", password=_PASSWORD, role=int(Roles.EDITOR)),
    )
    assert again.id == created.id
    assert again.role == int(Roles.ADMIN)
