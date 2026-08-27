"""Operation declarations for the ``oidc`` capability's public SSO routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of signing in through an external
identity provider without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

OIDC_AUTHORIZE = OperationDefinition(
    id="oidc.authorize", label="Start signing in with an external login provider"
)
OIDC_CALLBACK = OperationDefinition(
    id="oidc.callback",
    label="Finish signing in after the external login provider redirects back",
)

__all__ = ["OIDC_AUTHORIZE", "OIDC_CALLBACK"]
