"""Groups service — audited group CRUD + membership management.

Everything rides the kernel ``BaseService`` chokepoints, so every mutation is
audited and atomic: memberships are managed through a private member service
(``_save`` / ``_remove``), and deleting a group cascades — inside the *same*
write unit (ADR 0038) — to its membership rows and to the access grants naming
the group as subject, so no orphan grant keeps authorizing former members.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, func, select

from terp.core import AuditAction, BaseService, BaseUpdateSchema, NotFoundError

from terp.capabilities.access import AccessService
from terp.capabilities.identity import User

from terp.capabilities.groups.models import Group, GroupMember
from terp.capabilities.groups.schemas import GroupCreate, GroupMemberAdd, GroupUpdate


class _GroupMemberUpdate(BaseUpdateSchema):
    """Memberships are immutable (group + user) — nothing is updatable.

    Present only to satisfy ``BaseService``'s ``UpdateT`` type parameter; the
    router never exposes a member update route.
    """


class _MembersService(BaseService[GroupMember, GroupMemberAdd, _GroupMemberUpdate]):
    """Internal audited chokepoint for membership rows (not part of the public API)."""

    model = GroupMember


class GroupsService(BaseService[Group, GroupCreate, GroupUpdate]):
    model = Group

    def __init__(self) -> None:
        self._members = _MembersService()

    # -- membership -------------------------------------------------------------

    def _find_member(
        self, session: Session, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMember | None:
        return session.exec(
            self._members.base_query().where(
                GroupMember.group_id == group_id, GroupMember.user_id == user_id
            )
        ).first()

    def add_member(
        self, session: Session, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMember:
        """Add *user_id* to the group (idempotent: re-adding returns the existing row)."""
        self.get(session, group_id)  # 404 before any write when the group is gone
        existing = self._find_member(session, group_id, user_id)
        if existing is not None:
            return existing
        # Membership changes effective permissions — an audit-sensitive change, so
        # it routes through the audited chokepoint like a grant does.
        entity = GroupMember(group_id=group_id, user_id=user_id)
        return self._members._save(session, entity, AuditAction.CREATED)

    def remove_member(
        self, session: Session, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """Remove *user_id* from the group; unknown group or non-member is a 404."""
        self.get(session, group_id)
        existing = self._find_member(session, group_id, user_id)
        if existing is None:
            raise NotFoundError()
        self._members._remove(session, existing)

    def members_for(
        self, session: Session, group_id: uuid.UUID, *, skip: int, limit: int
    ) -> tuple[list[GroupMember], int]:
        """Paginated membership rows of one group (admin listing)."""
        self.get(session, group_id)
        return self._members._paginate(
            session,
            self._members.base_query().where(GroupMember.group_id == group_id),
            skip=skip,
            limit=limit,
        )

    def group_ids_for(self, session: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
        """The ids of every group *user_id* belongs to (the subject-expansion source)."""
        rows = session.exec(
            select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        ).all()
        return set(rows)

    def member_emails(
        self, session: Session, user_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Resolve member user ids to emails in one query (page-sized input).

        Backs the member listing's ``email`` enrichment: the UI shows accounts,
        not UUIDs, without holding a client-side directory. A vanished account
        (``user_id`` is FK-less) is simply absent from the map.
        """
        if not user_ids:
            return {}
        rows = session.exec(
            select(User.id, User.email).where(col(User.id).in_(user_ids))
        ).all()
        return dict(rows)

    # -- read helpers ------------------------------------------------------------

    def member_counts(
        self, session: Session, group_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Member totals for *group_ids* in one grouped query (no N+1 in listings)."""
        if not group_ids:
            return {}
        rows = session.exec(
            select(GroupMember.group_id, func.count())
            .where(col(GroupMember.group_id).in_(group_ids))
            .group_by(GroupMember.group_id)
        ).all()
        return dict(rows)

    # -- cascade -----------------------------------------------------------------

    def _after_write(self, session: Session, entity: Group, action: AuditAction) -> None:
        """Deleting a group cascades to its memberships and its grants, atomically.

        Runs inside the same write unit as the group's own ``DELETED`` record
        (ADR 0038): the nested audited removals join the transaction and flush
        before the group row is deleted, so the FK holds and a failure anywhere
        rolls back the whole cascade. Grants naming the group as subject are
        revoked through the access service, so a deleted group cannot keep
        authorizing its former members via a dangling subject id.
        """
        super()._after_write(session, entity, action)
        if action is not AuditAction.DELETED:
            return
        # Drain in batches until nothing remains: nested audited removals flush into
        # this same transaction, so each pass sees the prior pass's deletes. No size
        # cliff — a group of any size cascades completely or rolls back completely.
        while True:
            members, _total = self._members._paginate(
                session,
                self._members.base_query().where(GroupMember.group_id == entity.id),
                skip=0,
                limit=_CASCADE_BATCH,
            )
            if not members:
                break
            for member in members:
                self._members._remove(session, member)
        access = AccessService()
        while True:
            grants, _grant_total = access.list_for(
                session, entity.id, skip=0, limit=_CASCADE_BATCH
            )
            if not grants:
                break
            for grant in grants:
                access.delete(session, grant.id)


# Rows fetched per cascade pass (the loop above drains every pass until empty,
# so this bounds memory per pass — never the cascade's total size).
_CASCADE_BATCH = 1_000


__all__ = ["GroupsService"]
