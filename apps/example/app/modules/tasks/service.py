"""``tasks`` service — soft-delete is an auto-honored trait; only the status filter diverges.

``Task`` composes :class:`~terp.core.SoftDeleteMixin`, so ``BaseService`` excludes
deleted rows from every read and turns ``delete`` into a soft-delete automatically
(ADR 0010). The module therefore hand-writes **no** soft-delete code — it adds only
genuine business logic: an optional ``status`` filter on ``list``.
"""

from __future__ import annotations

from sqlmodel import Session

from terp.core import BaseService

from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskCreate, TaskUpdate


class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):
    model = Task

    def list(
        self,
        session: Session,
        *,
        skip: int,
        limit: int,
        status: str | None = None,
    ) -> tuple[list[Task], int]:
        query = self.base_query()
        if status is not None:
            query = query.where(Task.status == status)
        return self._paginate(session, query, skip=skip, limit=limit)
