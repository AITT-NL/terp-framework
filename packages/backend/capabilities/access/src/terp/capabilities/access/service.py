"""Access service — RBAC permission grants + the effective-permission check.

Grants are immutable (subject + permission), so writes are :meth:`grant`
(idempotent) and :meth:`revoke`; reads build on the kernel ``BaseService`` so
get / list / delete-by-id come for free. :meth:`has_permission` is the hot path
the ``require_permission`` dependency calls on every guarded request; it checks
the **expanded** subject set (the caller plus whatever registered subject
expanders add — e.g. the groups capability's memberships), so a grant to a
group is effective for its members with no extra call sites.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from terp.core import AuditAction, BaseService

from terp.capabilities.access.expansion import subject_ids_for
from terp.capabilities.access.models import Grant
from terp.capabilities.access.schemas import GrantCreate, GrantUpdate


class AccessService(BaseService[Grant, GrantCreate, GrantUpdate]):
    model = Grant

    def _find(
        self, session: Session, subject_id: uuid.UUID, permission: str
    ) -> Grant | None:
        return session.exec(
            select(Grant).where(
                Grant.subject_id == subject_id, Grant.permission == permission
            )
        ).first()

    def grant(self, session: Session, subject_id: uuid.UUID, permission: str) -> Grant:
        """Grant *permission* to *subject_id* (idempotent: a re-grant returns the existing row)."""
        existing = self._find(session, subject_id, permission)
        if existing is not None:
            return existing
        entity = Grant(subject_id=subject_id, permission=permission)
        # A grant is a security-sensitive change: route it through the audited
        # chokepoint so it lands an audit record (raw session writes do not).
        return self._save(session, entity, AuditAction.CREATED)

    def revoke(self, session: Session, subject_id: uuid.UUID, permission: str) -> bool:
        """Revoke *permission* from *subject_id*; return whether a grant was removed."""
        existing = self._find(session, subject_id, permission)
        if existing is None:
            return False
        # Revoking a permission is audit-sensitive too: go through _remove so the
        # DELETED record is emitted in the same transaction.
        self._remove(session, existing)
        return True

    def has_permission(
        self, session: Session, subject_id: uuid.UUID, permission: str
    ) -> bool:
        """True when *subject_id* holds *permission* (the deny-by-default check).

        Checks the expanded subject set: a direct grant, or a grant to any subject
        a registered expander maps the caller to (e.g. a group the user belongs
        to). With no expander registered this is exactly the direct-grant check.
        """
        subjects = subject_ids_for(session, subject_id)
        return (
            session.exec(
                select(Grant).where(
                    col(Grant.subject_id).in_(subjects),
                    Grant.permission == permission,
                )
            ).first()
            is not None
        )

    def permissions_for(self, session: Session, subject_id: uuid.UUID) -> set[str]:
        """Every permission *subject_id* holds — directly or through an expanded subject."""
        subjects = subject_ids_for(session, subject_id)
        rows = session.exec(
            select(Grant.permission).where(col(Grant.subject_id).in_(subjects))
        ).all()
        return set(rows)

    def list_for(
        self, session: Session, subject_id: uuid.UUID, *, skip: int, limit: int
    ) -> tuple[list[Grant], int]:
        """Paginated grants for *subject_id* (admin listing)."""
        return self._paginate(
            session,
            self.base_query().where(Grant.subject_id == subject_id),
            skip=skip,
            limit=limit,
        )


__all__ = ["AccessService"]
