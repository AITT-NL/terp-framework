"""What the self-service routes do (ADR 0196): open, prove, recover and close an account.

Two properties shape every method here.

**A request about an address answers the same way whether or not an account exists for
it.** Signing up for an address that has an account, or asking to reset one that has none,
does the same costly work as the other case, writes the same kind of row and returns
nothing that differs: the password is hashed and a token is sealed every time. Only the mail
differs, and the mail goes to the address, which is the one party allowed to know.

**A token works once.** Redeeming one requires both its seal (unexpired, for this purpose)
and its row (unused); redeeming spends the row, after the write it authorizes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session

from terp.core import AppError, AuthenticationError, InvalidTokenError, Principal, validate_password

from terp.capabilities.auth import hash_password, verify_password, verify_password_dummy
from terp.capabilities.identity import User
from terp.capabilities.mail import MailMessage, send_mail
from terp.capabilities.users.account_tokens import (
    RESET,
    SIGN_UP,
    AccountTokenService,
    open_account_token,
    seal_account_token,
)
from terp.capabilities.users.self_service import AccountDeletion, SelfService
from terp.capabilities.users.service import UsersService


class AccountSignsInElsewhereError(AppError):
    """409 — the account has no password here: it signs in through an identity provider."""

    status_code = 409
    code = "account_signs_in_elsewhere"
    default_message = (
        "This account signs in through an identity provider, so it cannot be closed with a "
        "password here. An administrator can close it."
    )


def _hours(declaration: SelfService, purpose: str) -> int:
    ttl = declaration.sign_up_ttl if purpose == SIGN_UP else declaration.reset_ttl
    return max(1, int(ttl.total_seconds() // 3600))


class AccountsService:
    """The self-service account operations, over the app's own users service."""

    def __init__(self, declaration: SelfService) -> None:
        self._declaration = declaration
        self._users = declaration.users
        self._tokens = AccountTokenService()

    # -- open --------------------------------------------------------------------------- #
    def request_sign_up(self, session: Session, email: str, password: str) -> None:
        """Mail *email* a sign-up token, or a notice that it already has an account.

        The policy check comes first and depends only on the password, so it says nothing
        about the address. Then the same work in both cases: hash, seal, mail, record.
        """
        validate_password(password)
        declaration = self._declaration
        token = seal_account_token(
            SIGN_UP, {"e": email, "h": hash_password(password)}, ttl=declaration.sign_up_ttl
        )
        messages = declaration.messages
        if self._users.get_by_email(session, email) is None:
            link = declaration.link(declaration.verify_path, token)
            text = messages.sign_up_text.format(link=link, hours=_hours(declaration, SIGN_UP))
            send_mail(session, MailMessage(to=[email], subject=messages.sign_up_subject, text=text))
        else:
            send_mail(
                session,
                MailMessage(to=[email], subject=messages.registered_subject, text=messages.registered_text),
            )
        self._tokens.record(session, token, purpose=SIGN_UP, ttl=declaration.sign_up_ttl)

    def verify_sign_up(self, session: Session, token: str) -> User:
        """Create the account a live sign-up token asks for, or refuse the token."""
        claims = open_account_token(SIGN_UP, token)
        row = self._tokens.live(session, token, purpose=SIGN_UP)
        email, hashed = _claim(claims, "e"), _claim(claims, "h")
        if row is None or email is None or hashed is None:
            raise InvalidTokenError()
        if self._users.get_by_email(session, email) is not None:
            # The account exists, so this token, or one for the same address, was redeemed.
            raise InvalidTokenError()
        user = self._users.create_verified(
            session,
            email=email,
            hashed_password=hashed,
            active=not self._declaration.requires_approval,
        )
        self._tokens.consume(session, row)
        return user

    # -- recover ------------------------------------------------------------------------ #
    def request_password_reset(self, session: Session, email: str) -> None:
        """Mail a reset token to an active account with a password; otherwise mail nothing.

        A token is sealed and a row is recorded either way, so the work and the write do
        not tell the cases apart.
        """
        declaration = self._declaration
        user = self._users.get_by_email(session, email)
        eligible = user is not None and user.is_active and user.hashed_password is not None
        subject_id = user.id if user is not None and eligible else uuid.uuid4()
        epoch = user.token_version if user is not None and eligible else 0
        token = seal_account_token(
            RESET, {"u": str(subject_id), "v": epoch}, ttl=declaration.reset_ttl
        )
        if eligible:
            link = declaration.link(declaration.reset_path, token)
            text = declaration.messages.reset_text.format(link=link, hours=_hours(declaration, RESET))
            send_mail(
                session, MailMessage(to=[email], subject=declaration.messages.reset_subject, text=text)
            )
        self._tokens.record(
            session, token, purpose=RESET, ttl=declaration.reset_ttl, user_id=subject_id if eligible else None
        )

    def confirm_password_reset(self, session: Session, token: str, password: str) -> None:
        """Set *password* on the account a live reset token names, or refuse the token.

        The token is bound to the account's token epoch, which the reset moves, so it works
        once and dies with any revocation that came after it was mailed.
        """
        claims = open_account_token(RESET, token)
        row = self._tokens.live(session, token, purpose=RESET)
        user = _user_for(self._users, session, claims)
        if (
            row is None
            or user is None
            or row.user_id != user.id
            or not user.is_active
            or user.hashed_password is None
            or claims is None
            or claims.get("v") != user.token_version
        ):
            raise InvalidTokenError()
        self._users.reset_password(session, user.id, password)
        self._tokens.consume(session, row)

    # -- close -------------------------------------------------------------------------- #
    def close(self, session: Session, principal: Principal, password: str) -> None:
        """Close the caller's own account, after checking their password again."""
        user = self._users.find(session, principal.id)
        if user is None or not user.is_active:
            verify_password_dummy()
            raise AuthenticationError()
        if user.hashed_password is None:
            raise AccountSignsInElsewhereError()
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError()
        self._users.close_account(
            session, user.id, remove=self._declaration.deletion is AccountDeletion.REMOVE
        )


def _claim(claims: dict[str, Any] | None, key: str) -> str | None:
    value = None if claims is None else claims.get(key)
    return value if isinstance(value, str) and value else None


def _user_for(users: UsersService, session: Session, claims: dict[str, Any] | None) -> User | None:
    raw = _claim(claims, "u")
    if raw is None:
        return None
    try:
        return users.find(session, uuid.UUID(raw))
    except ValueError:
        return None


__all__ = ["AccountSignsInElsewhereError", "AccountsService"]
