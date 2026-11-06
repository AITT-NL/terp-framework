@router.get('/{note_id}', response_model=NoteRead)
def get_note(note_id) -> NoteRead:
    return _service.get(note_id)
