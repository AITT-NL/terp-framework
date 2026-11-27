"""Accounts and refresh families used by the example app’s identity tests."""

from uuid import UUID

from sqlmodel import Session, select

from terp.capabilities.auth import refresh_token_digest
from terp.capabilities.identity import RefreshToken, User
from terp.capabilities.users import UsersService
from terp.core import AuditAction, Roles


class FixtureUsers(UsersService):
    def create_subject(
        self, session: Session, email: str, *, subject: UUID | None = None,
        rank: int = int(Roles.VIEWER), password_hash: str | None = None,
    ) -> User:
        """Create a subject with a known ID, custom rank or externally managed credential."""
        user = User(email=email, role=rank, hashed_password=password_hash)
        if subject is not None:
            user.id = subject
        return self._save(session, user, AuditAction.CREATED)

    def deactivate_at_current_epoch(self, session: Session, subject: UUID) -> User:
        """Represent the independently changed account used by the principal recheck tests."""
        user = self.get(session, subject)
        user.is_active = False
        return self._save(session, user, AuditAction.UPDATED)


def refresh_row(session: Session, raw: str) -> RefreshToken:
    return session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == refresh_token_digest(raw))
    ).one()
