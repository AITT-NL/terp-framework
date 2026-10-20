"""``notices`` router — thin reads and two writes over the module's services.

Uses the kernel seams only: ``SessionDep`` (the sole session source) and
``PaginationDep`` (mandatory pagination). Every route declares a ``response_model`` and
the operation it performs.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import Page, PaginationDep, SessionDep, operation

from app.modules.notices.jobs import request_snapshot
from app.modules.notices.schemas import (
    NoticeCreate,
    NoticeRead,
    SnapshotRead,
    SnapshotRequested,
)
from app.modules.notices.service import NoticeService, SnapshotService
from control_plane.app_operations import (
    NOTICES_CREATE,
    NOTICES_GET,
    NOTICES_LIST,
    SNAPSHOTS_LIST,
    SNAPSHOTS_REQUEST,
)

router = APIRouter(tags=["notices"])
_notices = NoticeService()
_snapshots = SnapshotService()


@router.get("/", response_model=Page[NoticeRead])
@operation(NOTICES_LIST)
def list_notices(session: SessionDep, pagination: PaginationDep) -> Page[NoticeRead]:
    rows, total = _notices.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[NoticeRead].of(
        [NoticeRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=NoticeRead, status_code=201)
@operation(NOTICES_CREATE)
def create_notice(payload: NoticeCreate, session: SessionDep) -> NoticeRead:
    return NoticeRead.model_validate(_notices.create(session, payload))


# Before `/{notice_id}`: routes match in order, and "snapshots" is not a UUID.
@router.get("/snapshots/", response_model=Page[SnapshotRead])
@operation(SNAPSHOTS_LIST)
def list_snapshots(session: SessionDep, pagination: PaginationDep) -> Page[SnapshotRead]:
    rows, total = _snapshots.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[SnapshotRead].of(
        [SnapshotRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/snapshots/", response_model=SnapshotRequested, status_code=202)
@operation(SNAPSHOTS_REQUEST)
def request_a_snapshot(session: SessionDep) -> SnapshotRequested:
    # Accepted, not done: the worker takes it, as it takes every tick of the schedule.
    return SnapshotRequested(job_id=request_snapshot(session))


@router.get("/{notice_id}", response_model=NoticeRead)
@operation(NOTICES_GET)
def get_notice(notice_id: uuid.UUID, session: SessionDep) -> NoticeRead:
    return NoticeRead.model_validate(_notices.get(session, notice_id))
