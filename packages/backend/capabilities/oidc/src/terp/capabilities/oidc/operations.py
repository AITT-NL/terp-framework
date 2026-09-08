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

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*OIDC_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
OIDC_OPERATIONS: tuple[OperationDefinition, ...] = (
    OIDC_AUTHORIZE,
    OIDC_CALLBACK,
)

__all__ = [
    "OIDC_AUTHORIZE",
    "OIDC_CALLBACK",
    "OIDC_OPERATIONS",
]
