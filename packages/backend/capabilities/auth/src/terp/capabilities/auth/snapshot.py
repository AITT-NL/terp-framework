"""Authority and revocation version from the same authentication snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session

from terp.core import AuthenticationError, Principal


@dataclass(frozen=True, kw_only=True)
class AuthenticatedPrincipal(Principal):
    """A principal and token epoch read together while authenticating its credential.

    Stores must capture this before returning from password, refresh, federated or
    machine authentication. Reading a new epoch later and pairing it with an old role
    would restore authority that an intervening security change revoked.
    """

    token_version: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.token_version) is not int or self.token_version < 0:
            raise ValueError("token_version must be a non-negative integer")


def resolve_token_version(
    session: Session,
    principal: Principal,
    resolver: Callable[[Session, Principal], int] | None,
) -> int:
    """Keep the authenticated epoch, refusing an intervening revoking change.

    A stateless custom authenticator can still return an ordinary ``Principal``.
    Wiring an epoch resolver, however, requires an authenticated snapshot: the
    framework cannot reconstruct which epoch the earlier credential check observed.
    """
    if resolver is not None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise AuthenticationError()
        if resolver(session, principal) != principal.token_version:
            raise AuthenticationError()
    return principal.token_version if isinstance(principal, AuthenticatedPrincipal) else 0


__all__ = ["AuthenticatedPrincipal", "resolve_token_version"]
