"""The lease table — one row per leasable resource, holding its current custody.

One record per ``(resource_kind, resource_key)``, created on first acquire and reused
forever after: a lease is not an event log, it is the *current* answer to "who holds this,
until when". A unique constraint on the pair is what makes that true under concurrency —
two workers racing to lease a resource nobody has yet cannot both insert, so exactly one
wins and the other re-reads and finds it taken.

Deliberately **not** a ``BaseTable``. Like :class:`~terp.capabilities.outbox.OutboxMessage`
it composes :class:`~terp.core.UUIDPrimaryKeyMixin` instead, because the optimistic
``version`` column would be the wrong arbiter here twice over: the lease's own
``(holder, epoch)`` fence is what decides a concurrent write, and a lease has to survive
its holder writing to the *business* row — an OCC token bumped by any unrelated update
would invalidate a live lease and strand the work it protects.

``epoch`` is the fence and only :meth:`~terp.capabilities.leases.store.DatabaseLeaseStore.
acquire` moves it: every **grant** increments it, a renewal does not. That is the whole
reason a paused worker cannot come back and clobber its successor — its epoch is one
behind, and every fenced statement carries ``AND epoch = :epoch``.

``touched_at`` records the last write of any kind, which is what makes the table
self-limiting: a row-shaped resource (one lease per domain row, ever) would otherwise grow
the table once per row processed, so a free record idle far longer than any TTL is purged.
Every caller-influenceable ``str`` column caps its length, so an oversized key fails in
Python rather than mid-transaction on a backend that enforces ``VARCHAR(n)``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from terp.core import LEASE_HOLDER_MAX, LEASE_KEY_MAX, LEASE_KIND_MAX, UUIDPrimaryKeyMixin


def _utc_now() -> datetime:
    """UTC ``now`` provider for this non-``BaseTable`` infrastructure row."""
    return datetime.now(UTC)


class ResourceLease(UUIDPrimaryKeyMixin, SQLModel, table=True):  # arch-allow-table-models-use-base-table: lease infra (like OutboxMessage) — the (holder, epoch) fence arbitrates writers, and an OCC version bumped by unrelated updates would invalidate a live lease (see module docstring)
    __tablename__ = "resource_lease"
    __table_args__ = (
        UniqueConstraint("resource_kind", "resource_key", name="uq_resource_lease_resource"),
    )

    resource_kind: str = Field(max_length=LEASE_KIND_MAX, index=True)
    resource_key: str = Field(max_length=LEASE_KEY_MAX)
    holder: str | None = Field(default=None, max_length=LEASE_HOLDER_MAX, index=True)
    epoch: int = Field(default=0)
    expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
        index=True,
    )
    acquired_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
    )
    touched_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
    )


__all__ = ["ResourceLease"]
