"""``journals`` router — thin CRUD over :class:`JournalService`.

Identical in shape to ``notes`` (kernel seams only: ``SessionDep`` + mandatory
``PaginationDep``, every route declares a ``*Read`` ``response_model``). The per-row
ownership gate is enforced centrally by ``BaseService`` from the ``OwnedMixin`` trait —
a non-owner ``PATCH`` / ``DELETE`` returns 403 — so the routes carry no ownership logic
of their own.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import Page, PaginationDep, SessionDep

from app.modules.journals.schemas import JournalCreate, JournalRead, JournalUpdate
from app.modules.journals.service import JournalService

router = APIRouter(tags=["journals"])
_service = JournalService()


@router.get("/", response_model=Page[JournalRead])
def list_journals(session: SessionDep, pagination: PaginationDep) -> Page[JournalRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[JournalRead].of(
        [JournalRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=JournalRead, status_code=201)
def create_journal(payload: JournalCreate, session: SessionDep) -> JournalRead:
    return JournalRead.model_validate(_service.create(session, payload))


@router.get("/{journal_id}", response_model=JournalRead)
def get_journal(journal_id: uuid.UUID, session: SessionDep) -> JournalRead:
    return JournalRead.model_validate(_service.get(session, journal_id))


@router.patch("/{journal_id}", response_model=JournalRead)
def update_journal(
    journal_id: uuid.UUID, payload: JournalUpdate, session: SessionDep
) -> JournalRead:
    return JournalRead.model_validate(_service.update(session, journal_id, payload))


@router.delete("/{journal_id}", status_code=204)
def delete_journal(journal_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, journal_id)
