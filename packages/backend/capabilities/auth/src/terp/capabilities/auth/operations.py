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

__all__ = ["AUTH_LOGIN", "AUTH_LOGOUT", "AUTH_ME", "AUTH_REFRESH", "AUTH_TOKEN"]
