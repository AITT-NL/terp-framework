import fastapi

from .service import NoteService


def publish(note_id: str, service: NoteService) -> dict:
    note = service.get(note_id)
    if note is None:
        raise fastapi.HTTPException(status_code=404, detail="Note not found")
    if note.published:
        raise fastapi.HTTPException(status_code=409, detail="Already published")
    return {"id": note_id}
