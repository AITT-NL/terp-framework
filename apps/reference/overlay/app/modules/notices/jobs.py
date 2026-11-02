"""The snapshot job: one egress call, its bytes into file storage, a row that points at them.

Declared here beside its handler and registered in ``control_plane/jobs.py``. The
scheduler enqueues it on its cron (``control_plane/schedules.py``), an editor can ask for
one now (``POST /api/v1/notices/snapshots/``), ``terp jobs run notices.snapshot.take``
enqueues one by hand, and in every case ``terp jobs worker`` runs it.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlmodel import Session

from terp.core import BaseSchema, JobContext, JobDefinition, enqueue

from terp.capabilities.files import FileService

from app.modules.notices import upstream
from app.modules.notices.schemas import SnapshotCreate
from app.modules.notices.service import SnapshotService

#: What a stored snapshot is called when the upstream names no media type of its own.
_FALLBACK_CONTENT_TYPE = "application/octet-stream"


class SnapshotTakePayload(BaseSchema):
    """Empty on purpose: the address is declared in code, never taken from a caller."""


def _content_type(headers: Mapping[str, str]) -> str:
    """The upstream's media type without its parameters, or the fallback."""
    raw = next((value for name, value in headers.items() if name.lower() == "content-type"), "")
    return raw.split(";", 1)[0].strip().lower()[:100] or _FALLBACK_CONTENT_TYPE


def take_snapshot(ctx: JobContext, payload: SnapshotTakePayload) -> None:
    """Fetch the upstream once and record what came back.

    A refused or failed call raises, so the outbox retries it with backoff and finally
    dead-letters it; a response of any status is a snapshot worth keeping.
    """
    response = upstream.client.get(upstream.UPSTREAM_URL)
    taken = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stored = FileService().store(
        ctx.session,
        filename=f"upstream-{taken}",
        content_type=_content_type(response.headers),
        source=io.BytesIO(response.content),
    )
    SnapshotService().create(
        ctx.session,
        SnapshotCreate(
            url=upstream.UPSTREAM_URL,
            status_code=response.status_code,
            size=stored.size,
            file_id=stored.id,
        ),
    )


SNAPSHOT_TAKE = JobDefinition(
    name="notices.snapshot.take",
    payload_schema=SnapshotTakePayload,
    handler=take_snapshot,
)


def request_snapshot(session: Session) -> str:
    """Enqueue one snapshot now, as a tick of the schedule would; return the job's id."""
    return enqueue(session, job=SNAPSHOT_TAKE, payload=SnapshotTakePayload())
