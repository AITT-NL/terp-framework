"""``notes`` router — thin CRUD over :class:`NoteService`.

Uses the kernel seams only: ``SessionDep`` (the sole session source) and
``PaginationDep`` (mandatory pagination). Every route declares a
``response_model``; no bare ORM rows leave the boundary.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import Page, PaginationDep, SessionDep

from app.modules.notes.schemas import NoteCreate, NoteRead, NoteUpdate
from app.modules.notes.service import NoteService

router = APIRouter(tags=["notes"])
_service = NoteService()


@router.get("/", response_model=Page[NoteRead])
def list_notes(session: SessionDep, pagination: PaginationDep) -> Page[NoteRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[NoteRead].of(
        [NoteRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=NoteRead, status_code=201)
def create_note(payload: NoteCreate, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.create(session, payload))


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: uuid.UUID, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.get(session, note_id))


@router.patch("/{note_id}", response_model=NoteRead)
def update_note(note_id: uuid.UUID, payload: NoteUpdate, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.update(session, note_id, payload))


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, note_id)
