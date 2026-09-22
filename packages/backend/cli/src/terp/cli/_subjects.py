"""Naming a subject the way an operator names it, shared by every command that writes access.

Extracted from ``terp grant`` when ``terp module-role`` needed the same thing. ADR 0089's
whole argument is that the UUID stays the storage key and stops being the interface: people
have an email address or the name of an integration, and a command that demands a UUID is a
command whose secure option is the expensive one. Two commands making that trade differently —
or one of them drifting — would put the cost straight back.
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid

from fastapi import FastAPI
from sqlmodel import Session

from terp.cli._appref import load_app, push_app_root


def load_app_for_cli(app_ref: str, app_root: str | pathlib.Path) -> FastAPI:
    """Import and compose the app at *app_root*, so its declarations can be read."""
    push_app_root(app_root)
    return load_app(app_ref)


def resolve_subject(session: Session, subject: str) -> tuple[uuid.UUID, str]:
    """Resolve *subject* — a UUID, a user email, or a service-account name.

    Access rows are keyed by a bare subject id with no foreign key, which is what lets a
    user, a service account and a group all be addressed the same way. The cost is that the
    id means nothing to a human, so the command accepts what people actually have and does
    the lookup itself. The returned label is for the message, not for storage.
    """
    with contextlib.suppress(ValueError):
        return uuid.UUID(subject), f"subject {subject}"

    if "@" in subject:
        from terp.capabilities.users import UsersService

        user = UsersService().get_by_email(session, subject)
        if user is None:
            raise SystemExit(f"no user with email {subject!r}")
        return user.id, f"user {subject!r}"

    from terp.capabilities.identity import ServiceAccountService

    account = ServiceAccountService().get_by_name(session, subject)
    if account is None:
        raise SystemExit(
            f"no service account named {subject!r} (pass an email for a user, a "
            "service-account name for a machine, or a subject UUID for anything else)"
        )
    return account.id, f"service account {subject!r}"


__all__ = ["load_app_for_cli", "resolve_subject"]
