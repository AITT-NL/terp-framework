@router.get('/', response_model=Page[NoteRead])
def list_notes() -> Page[NoteRead]:
    return Page()


@router.delete('/{note_id}', status_code=204)
def delete_note(note_id) -> None:
    _service.delete(note_id)
