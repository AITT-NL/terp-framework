"""Lease DTOs — the operator's read shape, plus the reap-cycle report.

Leases are taken by workers, never by clients, so there is no write DTO here: the router
exposes reads and one idempotent "reap now" action. What an operator needs from a read is
the thing raw columns do not quite say — *is this still alive?* — so
:class:`ResourceLeaseRead` carries an explicit ``expired`` flag computed against the same
clock the store uses, rather than leaving every caller to compare a timestamp against its
own idea of now and disagree.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from terp.core import BaseSchema

from terp.capabilities.leases.models import ResourceLease


class ResourceLeaseRead(BaseSchema):
    """One lease record as an operator sees it: who holds what, until when, still valid?"""

    id: uuid.UUID
    resource_kind: str
    resource_key: str
    holder: str | None
    epoch: int
    expires_at: datetime | None
    acquired_at: datetime | None
    touched_at: datetime
    created_at: datetime
    expired: bool

    @classmethod
    def of(cls, row: ResourceLease, *, now: datetime) -> ResourceLeaseRead:
        """Render *row*, deciding ``expired`` against *now* (the store's clock).

        A free record (nobody holds it) is reported ``expired=False``: there is no lease to
        have lapsed, and calling it expired would put every finished resource on the
        operator's "needs attention" list.
        """
        held = row.holder is not None and row.expires_at is not None
        expiry = row.expires_at
        expired = bool(
            held and _as_aware(expiry, now) <= now  # type: ignore[arg-type]
        )
        return cls(
            id=row.id,
            resource_kind=row.resource_kind,
            resource_key=row.resource_key,
            holder=row.holder,
            epoch=row.epoch,
            expires_at=row.expires_at,
            acquired_at=row.acquired_at,
            touched_at=row.touched_at,
            created_at=row.created_at,
            expired=expired,
        )


class LeaseReapReport(BaseSchema):
    """What one reap cycle did — the response to the operator's "reap now"."""

    scanned: int
    recovered: int
    released: int
    failed: int
    purged: int


def _as_aware(value: datetime, reference: datetime) -> datetime:
    """Re-attach *reference*'s timezone to a timestamp a backend handed back naive.

    SQLite drops the offset, so an expiry read back from it would raise the moment it is
    compared with the aware clock — which is the only comparison this DTO makes.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=reference.tzinfo)


__all__ = ["LeaseReapReport", "ResourceLeaseRead"]
