"""The ``SyncSource`` seam: how a sync reads System B and applies records to the local target.

An app implements one :class:`SyncSource` per entity type and registers it; the reconcile
engine (:class:`~terp.capabilities.sync.SyncService`) owns everything else — the run
bookkeeping, the mapping ledger, the record log. This is the seam that keeps the two
design invariants (§14):

* the **external read** of System B happens in :meth:`SyncSource.pull`, which the reconcile
  calls **inside the job handler** (a worker, post-commit) — never in an ``_after_write`` hook
  (the dual-write hazard the ADR-0040 review flagged); and
* the **local write** happens in :meth:`SyncSource.apply`, which MUST go through an audited
  ``BaseService`` so a synced row is actor / owner stamped and audited like any other write.

The source is resolved by ``entity_type`` from a small registry (the job carries the entity
type, not a closure — a remote worker resolves the source by name, like a job handler).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session


class SyncError(RuntimeError):
    """Raised when a sync source is unregistered, or a direction it does not support is run."""


@dataclass(frozen=True)
class RemoteRecord:
    """One record from System B: its remote id, a change-detecting checksum, and the payload.

    ``payload`` is plain JSON scalars (ids, not entities) — it crosses the job boundary and is
    handed to :meth:`SyncSource.apply` to upsert the local row. ``checksum`` lets the reconcile
    skip an unchanged record without deep-diffing.
    """

    remote_id: str
    checksum: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemotePage:
    """One page of remote records plus the cursor to resume from (the high-watermark)."""

    records: tuple[RemoteRecord, ...] = ()
    next_cursor: str | None = None


class SyncSource(ABC):
    """A registered source/target pair for one ``entity_type`` — the app implements it.

    Set ``entity_type`` on the subclass; implement :meth:`pull` (read System B) and
    :meth:`apply` (upsert the local row via an audited ``BaseService``). Override :meth:`push`
    only for a source that also pushes local changes outward (``SYNC_PUSH``); the default
    fails closed.
    """

    entity_type: str

    @abstractmethod
    def pull(self, cursor: str | None) -> RemotePage:
        """Read one page of remote records from *cursor* onward (the external System-B call)."""

    @abstractmethod
    def apply(
        self, session: Session, record: RemoteRecord, local_id: uuid.UUID | None
    ) -> uuid.UUID:
        """Create (``local_id`` is ``None``) or update the local entity; return its id.

        MUST persist through an audited ``BaseService`` so the synced row is stamped + audited.
        """

    def push(self, session: Session) -> int:  # noqa: ARG002 - default seam; overridden by push-capable sources
        """Push local changes to System B (``SYNC_PUSH``); default: unsupported. Returns count."""
        raise SyncError(f"sync source {self.entity_type!r} does not implement push")


_sources: dict[str, SyncSource] = {}


def register_sync_source(source: SyncSource) -> None:
    """Register *source* for its ``entity_type`` (replacing any prior registration).

    A capability registration (like a scope predicate): it persists across composed apps and is
    cleared only by :func:`reset_sync_sources`. An app calls this at composition time for each
    entity type it syncs.
    """
    _sources[source.entity_type] = source


def resolve_sync_source(entity_type: str) -> SyncSource:
    """Return the source registered for *entity_type*, or fail closed with :class:`SyncError`."""
    try:
        return _sources[entity_type]
    except KeyError:
        raise SyncError(
            f"no sync source registered for entity type {entity_type!r}; "
            "call register_sync_source(...) at composition time"
        ) from None


def registered_sync_sources() -> tuple[str, ...]:
    """The entity types with a registered source, in registration order."""
    return tuple(_sources)


def reset_sync_sources() -> None:
    """Clear the sync-source registry (a test seam; apps re-register at composition)."""
    _sources.clear()


__all__ = [
    "RemotePage",
    "RemoteRecord",
    "SyncError",
    "SyncSource",
    "register_sync_source",
    "registered_sync_sources",
    "reset_sync_sources",
    "resolve_sync_source",
]
