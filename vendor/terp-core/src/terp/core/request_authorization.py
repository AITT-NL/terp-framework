"""Request-local authorization inputs shared by the guard and dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session
from starlette.requests import HTTPConnection

from terp.core.permissions import PermissionModel

_AUTHORIZATION_SCOPE_KEY = "terp.authorization_context"


@dataclass(frozen=True)
class RequestAuthorization:
    """The mounted module's model and already constrained rank resolver.

    The composition root binds this before route dependencies execute. A module
    that has not opted into assignment supplies no resolver. A permission's
    dotted name does not select a module or confer assignment authority.
    """

    permission_model: PermissionModel | None
    module_rank: Callable[[Session, uuid.UUID], int] | None = None


def request_authorization(
    connection: HTTPConnection | None,
) -> RequestAuthorization | None:
    """Read the guard's inputs, or None outside a mounted guarded request."""
    context = (
        None if connection is None else connection.scope.get(_AUTHORIZATION_SCOPE_KEY)
    )
    return context if isinstance(context, RequestAuthorization) else None
