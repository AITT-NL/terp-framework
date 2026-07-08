"""``tasks`` router — thin CRUD with a ``status`` list filter."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from terp.core import Page, PaginationDep, SessionDep

from app.modules.tasks.schemas import TaskCreate, TaskRead, TaskUpdate
from app.modules.tasks.service import TaskService

router = APIRouter(tags=["tasks"])
_service = TaskService()


@router.get("/", response_model=Page[TaskRead])
def list_tasks(
    session: SessionDep,
    pagination: PaginationDep,
    status: str | None = Query(default=None),
) -> Page[TaskRead]:
    rows, total = _service.list(
        session, skip=pagination.skip, limit=pagination.limit, status=status
    )
    return Page[TaskRead].of(
        [TaskRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=TaskRead, status_code=201)
def create_task(payload: TaskCreate, session: SessionDep) -> TaskRead:
    return TaskRead.model_validate(_service.create(session, payload))


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: uuid.UUID, session: SessionDep) -> TaskRead:
    return TaskRead.model_validate(_service.get(session, task_id))


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: uuid.UUID, payload: TaskUpdate, session: SessionDep) -> TaskRead:
    return TaskRead.model_validate(_service.update(session, task_id, payload))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, task_id)
