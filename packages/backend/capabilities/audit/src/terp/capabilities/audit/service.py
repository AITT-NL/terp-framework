"""Read access to the audit log — one paginated, newest-first query.

The log is append-only (written by the sink), so this capability exposes only a
read path: a single, bounded list used by the admin router, optionally narrowed to
the one record a screen is about. Mirrors the kernel's pagination contract so the
trail is browsed like any other ``Page[T]``.
"""

from __future__ import annotations

from sqlmodel import Session, col, func, select

from terp.core import PaginationParams

from terp.capabilities.audit.models import AuditEvent


def list_audit_events(
    session: Session,
    *,
    pagination: PaginationParams,
    target_type: str | None = None,
    target_id: str | None = None,
) -> tuple[list[AuditEvent], int]:
    """Return one page of audit events, newest first, with the total count.

    ``target_type`` and ``target_id`` narrow the trail to the record a detail screen is
    about -- both columns are indexed for exactly this read. Either alone narrows too;
    neither returns the whole trail, as before.
    """
    conditions = []
    if target_type is not None:
        conditions.append(col(AuditEvent.target_type) == target_type)
    if target_id is not None:
        conditions.append(col(AuditEvent.target_id) == target_id)
    total = session.exec(select(func.count()).select_from(AuditEvent).where(*conditions)).one()
    rows = session.exec(
        select(AuditEvent)
        .where(*conditions)
        .order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


__all__ = ["list_audit_events"]

