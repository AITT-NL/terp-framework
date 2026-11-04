"""What the self-service routes do (ADR 0196): open, prove, recover and close an account.

Two properties shape every method here.

**A request about an address answers the same way whether or not an account exists for
it.** Signing up for an address that has an account, or asking to reset one that has none,
does the same work as the other case: a token is sealed, the same row is written and one
message is sent, every time. Only that message's words differ, and it goes to the address,
which is the one party allowed to know. Addresses are compared without regard to case, so
two spellings of one mailbox are one address.

**A token works once.** Redeeming one requires both its seal (unexpired, for this purpose)
and its row (unused); redeeming spends the row, after the write it authorizes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlmodel import Session

from terp.core import AppError, AuthenticationError, InvalidTokenError, Principal, validate_password

from terp.capabilities.auth import hash_password, verify_password, verify_password_dummy
from terp.capabilities.identity import User
from terp.capabilities.mail import MailMessage
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


def _lifetime(ttl: timedelta) -> str:
    """*ttl* in words for a mail, rounded down so a mail never promises more than the link has."""
    minutes = int(ttl.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes % 60:
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    hours = minutes // 60
    return "1 hour" if hours == 1 else f"{hours} hours"


class AccountsService:
    """The self-service account operations, over the app's own users service."""

    def __init__(self, declaration: SelfService) -> None:
        self._declaration = declaration
        self._users = declaration.users
        self._tokens = AccountTokenService()

    @staticmethod
    def _message(email: str, subject: str, text: str) -> MailMessage:
        return MailMessage(to=[email], subject=subject, text=text)

    # -- open --------------------------------------------------------------------------- #
    def request_sign_up(self, session: Session, email: str) -> None:
        """Mail *email* a sign-up token, or a notice that it already has an account.

        The same work in both cases: seal a token, record its row, send one message. The
        token carries the address and nothing else; the password is chosen when it is
        redeemed, by whoever reads this mail.
        """
        declaration = self._declaration
        token = seal_account_token(SIGN_UP, {"e": email}, ttl=declaration.sign_up_ttl)
        messages = declaration.messages
        if self._users.get_by_address(session, email) is None:
            link = declaration.link(declaration.verify_path, token)
            text = messages.sign_up_text.format(link=link, lifetime=_lifetime(declaration.sign_up_ttl))
            mail = self._message(email, messages.sign_up_subject, text)
        else:
            mail = self._message(email, messages.registered_subject, messages.registered_text)
        self._tokens.record(session, token, purpose=SIGN_UP, ttl=declaration.sign_up_ttl, mail=mail)

    def verify_sign_up(self, session: Session, token: str, password: str) -> User:
        """Open the account a live sign-up token asks for, with *password*, or refuse.

        The token is checked first, and only then the password, so a guess at a token is
        always a failed redemption and never a policy answer. A password the policy refuses
        leaves the token usable for a better one.
        """
        claims = open_account_token(SIGN_UP, token)
        row = self._tokens.live(session, token, purpose=SIGN_UP)
        email = _claim(claims, "e")
        if row is None or email is None:
            raise InvalidTokenError()
        if self._users.get_by_address(session, email) is not None:
            # The account exists, so this token, or one for the same mailbox, was redeemed.
            raise InvalidTokenError()
        validate_password(password)
        user = self._users.create_verified(
            session,
            email=email,
            hashed_password=hash_password(password),
            active=not self._declaration.requires_approval,
        )
        self._tokens.consume(session, row)
        return user

    # -- recover ------------------------------------------------------------------------ #
    def request_password_reset(self, session: Session, email: str) -> None:
        """Mail a reset link to an active account with a password, and a notice otherwise.

        Every request seals a token, records its row and sends one message, so neither the
        work, nor the write, nor a relay that is down tells the cases apart.
        """
        declaration = self._declaration
        messages = declaration.messages
        user = self._users.get_by_address(session, email)
        eligible = user is not None and user.is_active and user.hashed_password is not None
        subject_id = user.id if user is not None and eligible else uuid.uuid4()
        epoch = user.token_version if user is not None and eligible else 0
        token = seal_account_token(
            RESET, {"u": str(subject_id), "v": epoch}, ttl=declaration.reset_ttl
        )
        if eligible:
            link = declaration.link(declaration.reset_path, token)
            text = messages.reset_text.format(link=link, lifetime=_lifetime(declaration.reset_ttl))
            mail = self._message(email, messages.reset_subject, text)
        else:
            mail = self._message(email, messages.reset_unavailable_subject, messages.reset_unavailable_text)
        self._tokens.record(session, token, purpose=RESET, ttl=declaration.reset_ttl, mail=mail)

    def confirm_password_reset(self, session: Session, token: str, password: str) -> None:
        """Set *password* on the account a live reset token names, or refuse the token.

        The sealed token names the account and its token epoch, which the reset moves, so it
        works once and dies with any revocation that came after it was mailed; its row is
        spent as well.
        """
        claims = open_account_token(RESET, token)
        row = self._tokens.live(session, token, purpose=RESET)
        user = _user_for(self._users, session, claims)
        if (
            row is None
            or user is None
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
