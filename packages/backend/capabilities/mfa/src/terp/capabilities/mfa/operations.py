"""Operation declarations for the ``mfa`` capability's self-scoped routes.

Each route declares what it does in plain English (ADR 0102), so a non-technical reader
sees the effect of setting up, proving, inspecting or removing a second factor without
reading HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

MFA_STATUS = OperationDefinition(
    id="mfa.status", label="Check whether a second factor is set up"
)
MFA_ENROL = OperationDefinition(
    id="mfa.enrol", label="Start setting up a second factor"
)
MFA_CONFIRM = OperationDefinition(
    id="mfa.confirm", label="Finish setting up a second factor"
)
MFA_DISABLE = OperationDefinition(id="mfa.disable", label="Remove the second factor")

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by splatting
#: this (``*MFA_OPERATIONS``) rather than naming each constant, so a release that adds a
#: route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
MFA_OPERATIONS: tuple[OperationDefinition, ...] = (
    MFA_STATUS,
    MFA_ENROL,
    MFA_CONFIRM,
    MFA_DISABLE,
)

__all__ = [
    "MFA_CONFIRM",
    "MFA_DISABLE",
    "MFA_ENROL",
    "MFA_OPERATIONS",
    "MFA_STATUS",
]
