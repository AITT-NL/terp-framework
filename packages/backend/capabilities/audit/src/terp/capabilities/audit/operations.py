"""What the audit router's route does, for a non-technical reader (ADR 0102)."""

from __future__ import annotations

from terp.core import OperationDefinition

AUDIT_LIST_EVENTS = OperationDefinition(id="audit.list_events", label="View the audit trail")


__all__ = ["AUDIT_LIST_EVENTS"]
