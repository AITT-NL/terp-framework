"""The declaration that turns self-service accounts on (ADR 0196).

Off by default: an app that never builds the accounts module has none of its routes. The
declaration says why the app wants them, which store backs their throttle, where the links in
the mails point, whether new accounts wait for approval and what closing an account does. It
is checked when it is made; :func:`~terp.capabilities.users.build_accounts_module` checks the
rest, the parts that depend on the process it is built in.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from datetime import timedelta
from urllib.parse import urlsplit

from terp.core import ThrottleStore, settings

from terp.capabilities.users.service import UsersService

if TYPE_CHECKING:  # annotations only: the declaration reads no factor itself
    from terp.capabilities.auth import SecondFactor

_logger = logging.getLogger("terp.capabilities.users.self_service")

#: The longest a link may stay usable: a week for a sign-up, a day for a reset.
_SIGN_UP_TTL_CAP = timedelta(days=7)
_RESET_TTL_CAP = timedelta(days=1)


class AccountDeletion(enum.StrEnum):
    """What closing an account does to its row, once every session has ended."""

    #: Deactivate it and replace its address and password: the row stays for the
    #: references and the trail, and the person's data goes.
    SCRUB = "scrub"
    #: Delete the row. A reference to it must declare what that does (ADR 0133).
    REMOVE = "remove"


@dataclass(frozen=True)
class AccountMessages:
    """The mails the routes send. ``{link}`` and ``{lifetime}`` are filled in; the text is plain.

    ``{lifetime}`` is the link's lifetime in words ("24 hours", "1 hour", "30 minutes"),
    rounded down, so a mail never promises more time than the link has.

    Every request about an address sends that address exactly one of them, so neither the
    answer, nor its timing, nor a relay that is down tells whether an account exists: a
    sign-up gets the link or, for an address that has an account, the ``registered`` notice;
    a reset gets the link or, for an address with no active account that signs in with a
    password, the ``reset_unavailable`` notice.
    """

    sign_up_subject: str = "Confirm your address"
    sign_up_text: str = (
        "Someone, probably you, asked to open an account with this address.\n\n"
        "Open this link to confirm it and choose your password:\n{link}\n\n"
        "The link works once and expires in {lifetime}. If you did not ask, ignore this "
        "message: no account is opened unless the link is used."
    )
    registered_subject: str = "You already have an account"
    registered_text: str = (
        "Someone asked to open an account with this address, and it already has one. Sign in, "
        "or reset your password if you have forgotten it. If you did not ask, ignore this "
        "message."
    )
    reset_subject: str = "Reset your password"
    reset_text: str = (
        "Someone, probably you, asked to reset the password of the account with this "
        "address.\n\nOpen this link to choose a new one:\n{link}\n\n"
        "The link works once and expires in {lifetime}. If you did not ask, ignore this "
        "message: your password has not changed."
    )
    reset_unavailable_subject: str = "No password to reset"
    reset_unavailable_text: str = (
        "Someone asked to reset the password of an account with this address. No active "
        "account signs in with a password here, so nothing has changed. If you sign in "
        "through another provider, use it. If you did not ask, ignore this message."
    )


@dataclass(frozen=True)
class SelfService:
    """Self-service sign-up, proof of address, password reset and closing (ADR 0196).

    *users* is the app's own :class:`~terp.capabilities.users.UsersService`, wired with its
    refresh revoker, so closing an account and resetting a password end every session the
    same way an administrator's action does. *throttle_store* backs the backoff on every
    route. *link_base* is where the app's account pages live; a link puts the token in the
    URL fragment, which a browser never sends to a server. *second_factor* is the one the
    app's login consults, wired the same way (``build_login_module(..., second_factor=...)``):
    closing an account whose second factor is enrolled then asks for a code from it too.
    """

    reason: str
    users: UsersService
    throttle_store: ThrottleStore
    link_base: str
    requires_approval: bool = False
    deletion: AccountDeletion = AccountDeletion.SCRUB
    verify_path: str = "/account/verify"
    reset_path: str = "/account/reset"
    sign_up_ttl: timedelta = timedelta(hours=24)
    reset_ttl: timedelta = timedelta(hours=1)
    messages: AccountMessages = field(default_factory=AccountMessages)
    second_factor: SecondFactor | None = None

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError(
                "SelfService(reason=...) requires a non-empty justification: its routes let "
                "anyone open an account (ADR 0196)."
            )
        parts = urlsplit(self.link_base)
        if parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
            raise ValueError(
                f"SelfService.link_base must be an absolute http(s) URL with no query or "
                f"fragment, got {self.link_base!r}"
            )
        for name in ("verify_path", "reset_path"):
            if not getattr(self, name).startswith("/"):
                raise ValueError(f"SelfService.{name} must start with '/'")
        for name, cap in (("sign_up_ttl", _SIGN_UP_TTL_CAP), ("reset_ttl", _RESET_TTL_CAP)):
            ttl = getattr(self, name)
            if not timedelta(0) < ttl <= cap:
                raise ValueError(f"SelfService.{name} must be positive and at most {cap}")
        # Decided by an environment-INDEPENDENT predicate, as an OIDC provider's is, so the
        # answer exists where a gate can read it and not only on the production host.
        # Outside production the same state is said out loud rather than tolerated in
        # silence (ADR 0128).
        problems = self.production_problems()
        if problems:
            if settings.is_production:
                raise ValueError("; ".join(problems))
            _logger.warning(
                "self-service account links are PLAINTEXT in this deployment: %s. A "
                "production boot is REFUSED in this state.",
                "; ".join(problems),
            )

    def production_problems(self) -> list[str]:
        """What a production boot refuses about this declaration, environment-independent.

        A token rides the link's fragment, which a browser never sends, but a page loaded
        over plaintext can be rewritten in transit to read the fragment and post it
        elsewhere. So the links must be https wherever the mail is real.
        """
        if urlsplit(self.link_base).scheme == "https":
            return []
        return [
            f"SelfService.link_base must be https in production, got {self.link_base!r} (a "
            "page loaded over plaintext can be rewritten to read the token from the link)"
        ]

    def link(self, path: str, token: str) -> str:
        """The link a mail carries: the token in the fragment, never in the path or query."""
        return f"{self.link_base.rstrip('/')}{path}#token={token}"


__all__ = ["AccountDeletion", "AccountMessages", "SelfService"]
