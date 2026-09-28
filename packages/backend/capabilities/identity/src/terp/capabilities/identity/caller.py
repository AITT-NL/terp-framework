"""Who is calling, named the way people name them — a dependency for module code (ADR 0162).

A route gets a :class:`~terp.core.Principal`, which carries an id, a role and a kind: enough
for the guard, and nothing a person would recognise. When a module has to say *who* did
something in words — the operator on a decision it forwards, the account on a message it
sends — it needs the name the platform addresses that subject by: a user's email, or a
service account's name, the same two that ``terp grant`` and ``terp module-role`` accept
(ADR 0089).

Before this, the only way to get one was to construct an ``IdentityService`` inside the
module and look the user up, which wires a second copy of something the composition root
already built, and handles a service account not at all. The easier ways out are worse: a
"decided by" field taken from the request body is whatever the client says, and an email in
the token's claims is stale the moment it changes. So the platform answers the question once::

    from terp.capabilities.identity import CallerDep

    @router.post("/{name}/pause", status_code=204)
    def pause(name: str, caller: CallerDep, session: SessionDep) -> None:
        service.pause(session, name, decided_by=caller.name)

It reads the live row, so a renamed account is named as it is now, and it needs no wiring:
it resolves through the kernel's ``get_principal`` seam, which ``create_app`` points at the
configured provider, and the request's own session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from terp.capabilities.auth import SubjectKind
from terp.core import AuthenticationError, Principal, SessionDep, get_principal

from terp.capabilities.identity.models import ServiceAccount, User


@dataclass(frozen=True)
class Caller:
    """The authenticated caller, as a person would name them."""

    #: The stable key — what to store when a record must point at who did it.
    id: uuid.UUID
    #: What to show or send: a user's email, or a service account's name.
    name: str


def current_caller(
    session: SessionDep,
    principal: Annotated[Principal | None, Depends(get_principal)],
) -> Caller:
    """Resolve the request's principal to a :class:`Caller`, or refuse it as unauthenticated.

    An unauthenticated request is refused, and so is a principal whose row no longer exists —
    a token for a removed subject reaching a provider that does not check the store — rather
    than being named by an id nobody can read. The row is looked up in the table the
    principal's kind says it lives in; a service account is never looked up as a user.
    """
    if principal is None:
        raise AuthenticationError()
    if principal.kind == SubjectKind.SERVICE:
        account = session.get(ServiceAccount, principal.id)
        name = None if account is None else account.name
    else:
        user = session.get(User, principal.id)
        name = None if user is None else user.email
    if name is None:
        raise AuthenticationError()
    return Caller(id=principal.id, name=name)


#: The dependency, annotated: take a ``caller: CallerDep`` parameter on a route.
CallerDep = Annotated[Caller, Depends(current_caller)]

__all__ = ["Caller", "CallerDep", "current_caller"]
