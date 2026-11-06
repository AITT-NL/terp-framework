from fastapi import HTTPException

from .service import NoteService


def import_note(payload: str, service: NoteService) -> dict:
    try:
        note = service.import_note(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc
    return {"id": note.id}
