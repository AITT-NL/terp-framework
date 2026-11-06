import uuid


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: uuid.UUID) -> NoteRead:
    return NoteRead()
