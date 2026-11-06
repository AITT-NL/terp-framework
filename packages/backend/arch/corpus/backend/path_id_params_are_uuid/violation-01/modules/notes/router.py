import uuid


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: int) -> NoteRead:
    return NoteRead()
