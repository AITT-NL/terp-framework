"""SSO request/response DTOs."""

from __future__ import annotations

from sqlmodel import Field

from terp.core import BaseSchema


class AuthorizationRequest(BaseSchema):
    """The IdP authorize URL for one freshly-opened flow — the client navigates to it.

    The binding secrets (``state`` server-side lookup key aside, the ``nonce`` and the
    PKCE verifier) stay server-side in the state store; only the URL leaves.
    """

    provider: str
    authorization_url: str


class OIDCCallbackRequest(BaseSchema):
    """What the IdP appended to the redirect URI, relayed by the client."""

    code: str = Field(max_length=4096)
    state: str = Field(max_length=512)


__all__ = ["AuthorizationRequest", "OIDCCallbackRequest"]
