"""Read access to the audit log — one paginated, newest-first query.

The log is append-only (written by the sink), so this capability exposes only a
read path: a single, bounded list used by the admin router. Mirrors the kernel's
pagination contract so the trail is browsed like any other ``Page[T]``.
"""

from __future__ import annotations

from sqlmodel import Session, col, func, select

from terp.core import PaginationParams

from terp.capabilities.audit.models import AuditEvent


def list_audit_events(
    session: Session, *, pagination: PaginationParams
) -> tuple[list[AuditEvent], int]:
    """Return one page of audit events, newest first, with the total count."""
    total = session.exec(select(func.count()).select_from(AuditEvent)).one()
    rows = session.exec(
        select(AuditEvent)
        .order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


__all__ = ["list_audit_events"]

