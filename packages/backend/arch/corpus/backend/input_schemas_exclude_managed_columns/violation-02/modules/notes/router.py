import uuid

from terp.core import BaseSchema


class NotePayload(BaseSchema):
    owner_id: uuid.UUID
    tenant_id: uuid.UUID
    title: str


@router.post('/', response_model=NoteRead)
def create_note(payload: NotePayload) -> NoteRead:
    return NoteRead()
