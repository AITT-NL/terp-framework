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

from pydantic import Field

from terp.core import LEASE_HOLDER_MAX, BaseSchema

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


class LeaseHeartbeat(BaseSchema):
    """A holder reporting that it is still working, and how long it still needs.

    The fence travels in the body because it is what makes this safe: ``epoch`` is the
    lease's generation, so a heartbeat from a holder whose claim was already reaped and
    re-granted matches nothing and extends nothing. Without it a late heartbeat from a
    process that had been declared dead would silently take the resource back from its
    successor — the split brain the fence exists to prevent.
    """

    #: The holder id this caller claims to be. Bounded by the platform's own column limit
    #: rather than a number repeated here, so the two cannot drift.
    holder: str = Field(min_length=1, max_length=LEASE_HOLDER_MAX)
    #: The generation of the lease being renewed — the fence.
    epoch: int = Field(ge=1)
    #: How much longer the holder needs. A heartbeat sets a new expiry rather than adding
    #: to the old one, so a holder that goes quiet lapses on its LAST reported need.
    ttl_seconds: float = Field(gt=0)


class LeaseHeartbeatAccepted(BaseSchema):
    """When the renewed lease now lapses — the deadline the holder must beat."""

    resource_kind: str
    resource_key: str
    holder: str
    epoch: int
    expires_at: datetime
