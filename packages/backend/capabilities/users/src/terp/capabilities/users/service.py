"""Users service — admin management over the identity ``User`` store.

Builds on identity's persisted ``User``: every write routes through the audited
``BaseService`` chokepoint, so admin provisioning, role/email edits, deactivation,
and password resets each land an audit record (and a soft-delete-style
deactivation is preferred over a hard delete). Passwords are hashed via the auth
capability. Reads (``list`` / ``get``) are inherited unchanged.

A safety invariant guards the admin surface itself: an action that would leave the
system with **no active administrator** — deactivating or demoting the last active
admin — is refused (fail-closed), so an admin can never lock every administrator
out of the admin-only routes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from threading import RLock
from typing import ClassVar

from sqlmodel import Session, col, select

from terp.capabilities.auth import hash_password
from terp.core import AppError, AuditAction, BaseService, Roles, validate_password

from terp.capabilities.identity import User
from terp.capabilities.users.schemas import UserAdminUpdate, UserProvision

_ADMIN_RANK = int(Roles.ADMIN)


class LastAdminError(AppError):
    """409 — the action would leave the system with no active administrator."""

    status_code = 409
    code = "last_admin_protected"
    default_message = (
        "This action would remove the last active administrator and is refused; "
        "promote or activate another administrator first."
    )


class SelfAdminActionError(AppError):
    """409 — an administrator may not deactivate or demote their own account."""

    status_code = 409
    code = "self_admin_action_protected"
    default_message = (
        "Administrators cannot deactivate or demote their own administrator account; "
        "ask another active administrator to perform this action."
    )


class UsersService(BaseService[User, UserProvision, UserAdminUpdate]):
    model = User
    _admin_invariant_lock: ClassVar[RLock] = RLock()

    def __init__(
        self, refresh_revoker: Callable[[Session, uuid.UUID], None] | None = None
    ) -> None:
        """Optionally wire a *refresh_revoker* (ADR 0054).

        When supplied, every audited user security update also revokes the user's
        refresh-token families in ``_after_write``, so a logout / deactivate / demote /
        password-reset kills *both* the access-token epoch and the refresh cookie in the
        same transaction. Unwired (the default), revocation is ADR 0031's epoch-only
        behaviour, unchanged.
        """
        self._refresh_revoker = refresh_revoker

    def create(self, session: Session, data: UserProvision) -> User:
        """Provision a new user (password hashed), audited via the write chokepoint.

        The credential boundary enforces the app's ``PasswordPolicy`` (ADR 0032): a weak
        password is refused with the uniform ``WeakPasswordError`` before it is hashed; the
        DTO's ``max_length`` stays the separate DoS cap.
        """
        validate_password(data.password)
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role=int(data.role),
        )
        return self._save(session, user, AuditAction.CREATED)

    def get_by_email(self, session: Session, email: str) -> User | None:
        """Find a user by email, or ``None`` — the lookup the bootstrap / seed paths share."""
        return session.exec(select(User).where(User.email == email)).first()

    def list_matching(
        self, session: Session, *, email: str, skip: int, limit: int
    ) -> tuple[list[User], int]:
        """Paginated users whose email contains *email* (case-insensitive).

        The directory-lookup primitive behind the admin surface's ``?email=``
        filter: member pickers and admin searches resolve an account by typing
        part of its address instead of paging through the whole directory.
        Builds on ``base_query`` like every read.
        """
        return self._paginate(
            session,
            self.base_query().where(col(User.email).icontains(email)),
            skip=skip,
            limit=limit,
        )

    def ensure_user(self, session: Session, data: UserProvision) -> User:
        """Idempotent provisioning: return the existing user for ``data.email``, else create one.

        The create-if-absent primitive for bootstrap and seed paths (``terp user create`` /
        ``terp seed``): the lookup + audited create live here once, so a caller never
        re-implements the query. An already-present user is returned untouched (no password
        reset, no role change), so re-running a seed is a safe no-op.
        """
        existing = self.get_by_email(session, data.email)
        if existing is not None:
            return existing
        return self.create(session, data)

    def update(
        self,
        session: Session,
        entity_id: uuid.UUID,
        data: UserAdminUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        """Admin edit (email / role) with OCC — refusing to demote the last admin.

        A role or email change is security-relevant (a demotion, or an email change that
        re-tenants the user), so it bumps the token epoch in the **same** write — revoking
        the user's outstanding tokens at once (ADR 0031) instead of leaving the old rank /
        tenant live for the access-token lifetime.
        """
        with self._admin_invariant_lock:
            user = self.get(session, entity_id)
            if data.role is not None and int(data.role) < _ADMIN_RANK:
                if actor_id is not None and user.id == actor_id:
                    raise SelfAdminActionError()
                if self._is_last_active_admin(session, user):
                    raise LastAdminError()
            # Do the OCC check before bumping the token epoch. Bumping first leaves a
            # dirty object behind if the stale-version check raises; a later commit on the
            # same session could otherwise revoke sessions even though the update failed.
            if user.version != data.version:
                from terp.core import StaleDataError

                raise StaleDataError()
            patch = self._without_managed_columns(data.model_dump(exclude_unset=True))
            for key, value in patch.items():
                setattr(user, key, value)
            self._bump_token_version(user)
            return self._save(session, user, AuditAction.UPDATED)

    def set_active(
        self,
        session: Session,
        user_id: uuid.UUID,
        *,
        active: bool,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        """Deactivate / reactivate a user (audited) — preferred over a hard delete.

        Deactivating the last active administrator is refused, so the admin-only
        surface can never be locked out for everyone. A deactivation also bumps the
        token epoch, so the user's outstanding tokens stop working at once — defense in
        depth atop the principal seam's mid-session ``is_active`` re-check (ADR 0031).
        """
        with self._admin_invariant_lock:
            user = self.get(session, user_id)
            if not active:
                if actor_id is not None and user.id == actor_id:
                    raise SelfAdminActionError()
                if self._is_last_active_admin(session, user):
                    raise LastAdminError()
                self._bump_token_version(user)
            user.is_active = active
            return self._save(session, user, AuditAction.UPDATED)

    def reset_password(
        self, session: Session, user_id: uuid.UUID, new_password: str
    ) -> User:
        """Set a new password for a user (hashed, audited).

        Resetting the password revokes the user's outstanding tokens (the epoch bump),
        so a live session on the old credential cannot survive the reset (ADR 0031).
        """
        validate_password(new_password)
        user = self.get(session, user_id)
        user.hashed_password = hash_password(new_password)
        self._bump_token_version(user)
        return self._save(session, user, AuditAction.UPDATED)

    def revoke_sessions(self, session: Session, user_id: uuid.UUID) -> None:
        """Invalidate a user's outstanding tokens — the logout / forced-logout write.

        Bumps the token epoch through the audited chokepoint, so every token minted
        before this is rejected at its next request (ADR 0031). The auth capability's
        ``/logout`` route wires this as its ``revoke_sessions`` seam (auth does not own
        the store it must write).
        """
        user = self.get(session, user_id)
        self._bump_token_version(user)
        self._save(session, user, AuditAction.UPDATED)

    def _after_write(self, session: Session, entity: User, action: AuditAction) -> None:
        """Join refresh-token revocation to the audited user write (ADR 0054).

        ``BaseService._save`` calls this after staging the ``identity_user`` update + audit
        record and before the single outer commit. That makes the access-token epoch bump,
        audit trail, and refresh-family revocation one atomic write unit; if any part raises,
        none commits.
        """
        super()._after_write(session, entity, action)
        if action is AuditAction.UPDATED and self._refresh_revoker is not None:
            self._refresh_revoker(session, entity.id)

    @staticmethod
    def _bump_token_version(user: User) -> None:
        """Advance the token epoch (ADR 0031); refresh families revoke in ``_after_write``.

        The refresh-token revoker (when wired) runs from :meth:`_after_write`, inside the
        same ``BaseService._save`` transaction as the audited user update.
        """
        user.token_version += 1

    def _is_last_active_admin(self, session: Session, user: User) -> bool:
        """True when *user* is an active admin and no other active admin remains."""
        if not (user.is_active and user.role >= _ADMIN_RANK):
            return False
        return self._active_admin_count(session) <= 1

    def _active_admin_count(self, session: Session) -> int:
        """Count active admins, locking those rows where the database supports it."""
        admins = session.exec(
            select(User)
            .where(User.is_active, User.role >= _ADMIN_RANK)  # type: ignore[arg-type]
            .with_for_update()
        ).all()
        return len(admins)
