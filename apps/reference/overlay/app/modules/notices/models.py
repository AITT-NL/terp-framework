"""The reference app's two records.

A :class:`Notice` is posted and mailed to its recipient. A :class:`Snapshot` is what the
scheduled job brought back from the one upstream host the app may call: the response's
status and size here, its bytes in file storage, reached through a declared ``FileRef``.

Both compose ``OwnedMixin``: a module that declares background jobs is one whose rows
belong to someone (``no_manual_ownership_checks``), so a notice belongs to whoever posted
it and a snapshot to the system actor its job runs as (``JOB_SYSTEM_ACTOR_ID``).
"""

from __future__ import annotations

import uuid

from sqlmodel import Field

from terp.core import BaseTable, OwnedMixin

from terp.capabilities.files import FileRef


class Notice(BaseTable, OwnedMixin, table=True):
    """``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited — never redeclared."""

    __tablename__ = "notice"

    title: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    recipient: str = Field(max_length=254)


class Snapshot(BaseTable, OwnedMixin, table=True):
    """One fetch of the upstream document. Append-only: a snapshot is never edited."""

    __tablename__ = "notice_snapshot"

    url: str = Field(max_length=2048)
    status_code: int
    size: int
    file_id: uuid.UUID | None = FileRef()
