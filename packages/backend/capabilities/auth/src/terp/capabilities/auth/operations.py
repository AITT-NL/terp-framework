"""Operation declarations for the ``auth`` capability's sign-in routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of signing in, staying signed in, or
signing out without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

AUTH_LOGIN = OperationDefinition(
    id="auth.login", label="Sign in with an email and password"
)
AUTH_TOKEN = OperationDefinition(
    id="auth.token", label="Sign in a connected application with its own login details"
)
AUTH_REFRESH = OperationDefinition(
    id="auth.refresh", label="Stay signed in without entering a password again"
)
AUTH_LOGOUT = OperationDefinition(id="auth.logout", label="Sign out of the current session")
AUTH_ME = OperationDefinition(id="auth.me", label="View your own profile")

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*AUTH_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0124).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
AUTH_OPERATIONS: tuple[OperationDefinition, ...] = (
    AUTH_LOGIN,
    AUTH_TOKEN,
    AUTH_REFRESH,
    AUTH_LOGOUT,
    AUTH_ME,
)

__all__ = [
    "AUTH_LOGIN",
    "AUTH_LOGOUT",
    "AUTH_ME",
    "AUTH_OPERATIONS",
    "AUTH_REFRESH",
    "AUTH_TOKEN",
]
