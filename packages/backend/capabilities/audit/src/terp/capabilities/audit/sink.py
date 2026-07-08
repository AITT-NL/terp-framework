"""The durable audit sink — turns a core :class:`AuditRecord` into a stored row.

``create_app(audit_sink=persist_audit)`` installs this on the core audit seam, so
every ``BaseService`` mutation appends an :class:`AuditEvent` **inside the caller's
transaction** — the row commits atomically with the business write, and a failure
here aborts the mutation rather than losing the trail (fail-closed).

The record reaches this point already centrally redacted (see
:meth:`terp.core.AuditPolicy.redact`); the sink only clips caller-influenceable
strings to their column bounds and strips NUL bytes, so a hostile or oversized
value can never break the INSERT — the audit trail must outlive bad input.
"""

from __future__ import annotations

from sqlmodel import Session

from terp.core import AuditPolicy, AuditRecord, DurableAuditSink

from terp.capabilities.audit.models import AuditEvent


def _clip(value: str | None, limit: int) -> str | None:
    """Strip NUL bytes and clamp *value* to a bounded column's *limit*."""
    if value is None:
        return None
    return value.replace("\x00", "")[:limit]


def _persist_audit(session: Session, record: AuditRecord, policy: AuditPolicy) -> None:
    """Append *record* to the audit log within the caller's transaction (no commit).

    The chokepoint that emitted *record* owns the commit, so the audit row rides
    the same unit of work as the business mutation. *policy* is accepted to satisfy
    the sink contract; redaction was already applied centrally before this call.
    """
    event = AuditEvent(
        action=record.action.value,
        target_type=_clip(record.target_type, 128) or "",
        target_id=_clip(record.target_id, 128) or "",
        actor_id=record.actor_id,
        request_id=_clip(record.request_id, 64),
        payload=dict(record.payload) if record.payload else None,
    )
    session.add(event)  # arch-allow-mutations-emit-audit: this IS the durable audit sink, the base of the write stack — it cannot route through BaseService


persist_audit = DurableAuditSink("terp.capabilities.audit.persist_audit", _persist_audit)


__all__ = ["persist_audit"]
