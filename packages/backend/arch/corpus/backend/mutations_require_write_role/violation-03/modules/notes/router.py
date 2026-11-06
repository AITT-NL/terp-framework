@router.patch('/{note_id}', response_model=NoteRead)
def update_note(note_id, payload) -> NoteRead:
    return NoteRead()
