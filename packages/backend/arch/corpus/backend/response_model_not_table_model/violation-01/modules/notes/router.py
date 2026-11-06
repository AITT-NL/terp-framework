@router.get('/{note_id}', response_model=Note)
def get_note(note_id) -> Note:
    return _service.get(note_id)
