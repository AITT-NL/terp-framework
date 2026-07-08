"""``terp user create`` — provision (or confirm) a user straight against the app's store.

Closes the first-administrator bootstrap: the admin-only ``/users`` API cannot mint the
*first* administrator (no admin exists yet to authorize the call), so an operator needs an
out-of-band seam. This builds the app (so ``create_app`` has configured the engine and the
durable audit sink), opens a session on the live database, and provisions through the
audited :class:`~terp.capabilities.users.UsersService` chokepoint — so even the bootstrap
admin lands an audit row and is held to the app's ``PasswordPolicy``.

The password is read from an environment variable (default ``TERP_USER_PASSWORD``) or an
interactive prompt — never a command-line argument, so it cannot leak into shell history or
the process table. Re-running for an existing email is a no-op (idempotent).
"""

from __future__ import annotations

import contextlib
import getpass
import os
import pathlib
from collections.abc import Callable

from terp.cli._appref import load_app, push_app_root
from terp.core import Roles
from terp.core.db import get_session

_ROLE_ALIASES = {
    "viewer": int(Roles.VIEWER),
    "editor": int(Roles.EDITOR),
    "admin": int(Roles.ADMIN),
}


def resolve_role(value: str) -> int:
    """Resolve a ``--role`` value: a name (viewer / editor / admin) or an integer rank."""
    key = value.strip().lower()
    if key in _ROLE_ALIASES:
        return _ROLE_ALIASES[key]
    try:
        rank = int(value)
    except ValueError:
        raise SystemExit(
            f"--role must be viewer / editor / admin or an integer rank, not {value!r}"
        ) from None
    if rank < 0:
        raise SystemExit("--role rank must be >= 0")
    return rank


def read_password(env_var: str) -> str:
    """Read the new password from *env_var*, falling back to an interactive prompt."""
    password = os.environ.get(env_var)
    if password:
        return password
    return getpass.getpass("New user password: ")


def create_user_command(
    email: str,
    *,
    role: str = "admin",
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    password_env: str = "TERP_USER_PASSWORD",  # noqa: S107 - the env var *name*, not a secret
    password_reader: Callable[[str], str] = read_password,
) -> str:
    """Build *app_ref*, then create (or confirm) user *email* with *role*, audited.

    Idempotent: an already-present email is reported and left unchanged. The password comes
    from *password_env* or an interactive prompt via *password_reader* (injected in tests),
    and its strength is enforced by the ``UsersService`` write chokepoint — a weak password
    fails closed as a clean CLI error.
    """
    push_app_root(app_root)
    load_app(app_ref)

    from terp.capabilities.users import UserProvision, UsersService
    from terp.core import AppError

    rank = resolve_role(role)
    service = UsersService()
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        existing = service.get_by_email(session, email)
        if existing is not None:
            return f"user {email!r} already exists (id {existing.id}); left unchanged"
        password = password_reader(password_env)
        try:
            user = service.create(
                session, UserProvision(email=email, password=password, role=rank)
            )
        except AppError as exc:
            raise SystemExit(f"could not create user {email!r}: {exc}") from exc
    return f"created user {email!r} (id {user.id}, role rank {rank})"
