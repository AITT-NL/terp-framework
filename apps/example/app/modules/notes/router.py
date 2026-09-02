"""``notes`` router — thin CRUD over :class:`NoteService`.

Uses the kernel seams only: ``SessionDep`` (the sole session source) and
``PaginationDep`` (mandatory pagination). Every route declares a
``response_model``; no bare ORM rows leave the boundary.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from terp.core import Page, PaginationDep, SessionDep, operation

from terp.capabilities.access import require_permission

from app.modules.notes.schemas import NoteCreate, NoteRead, NoteUpdate
from app.modules.notes.service import NoteService
from control_plane.operations import (
    NOTES_CREATE,
    NOTES_DELETE,
    NOTES_GET,
    NOTES_LIST,
    NOTES_UPDATE,
)
from control_plane.permissions import NOTES_DELETE_PERMISSION

router = APIRouter(tags=["notes"])
_service = NoteService()


@router.get("/", response_model=Page[NoteRead])
@operation(NOTES_LIST)
def list_notes(session: SessionDep, pagination: PaginationDep) -> Page[NoteRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[NoteRead].of(
        [NoteRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=NoteRead, status_code=201)
@operation(NOTES_CREATE)
def create_note(payload: NoteCreate, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.create(session, payload))


@router.get("/{note_id}", response_model=NoteRead)
@operation(NOTES_GET)
def get_note(note_id: uuid.UUID, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.get(session, note_id))


@router.patch("/{note_id}", response_model=NoteRead)
@operation(NOTES_UPDATE)
def update_note(note_id: uuid.UUID, payload: NoteUpdate, session: SessionDep) -> NoteRead:
    return NoteRead.model_validate(_service.update(session, note_id, payload))


@router.delete(
    "/{note_id}",
    status_code=204,
    dependencies=[Depends(require_permission(NOTES_DELETE_PERMISSION))],
)
@operation(NOTES_DELETE)
# The module's write tier AND a named grant. Every other route here is gated by the
# module `Policy` alone, which asks "may this person change notes?". Destroying one is a
# different decision and the tier cannot express it: either every editor may delete or
# nobody may. So this route adds `notes.delete` on top — an editor may write, and may
# delete only once someone has said so (`terp grant add <who> notes.delete`).
#
# Deliberately a comment, not a docstring: FastAPI publishes a route docstring as the
# OpenAPI `description`, and ADR 0102 already makes the declared operation the one answer
# to "what does this route do". A second answer in the contract is the drift that
# decision exists to prevent — and it is what the committed spec would have recorded.
def delete_note(note_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, note_id)
