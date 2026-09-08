"""What the audit router's route does, for a non-technical reader (ADR 0102)."""

from __future__ import annotations

from terp.core import OperationDefinition

AUDIT_LIST_EVENTS = OperationDefinition(id="audit.list_events", label="View the audit trail")

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*AUDIT_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
AUDIT_OPERATIONS: tuple[OperationDefinition, ...] = (
    AUDIT_LIST_EVENTS,
)

__all__ = [
    "AUDIT_LIST_EVENTS",
    "AUDIT_OPERATIONS",
]
