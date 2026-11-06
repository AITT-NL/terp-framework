@router.get('/refresh', response_model=NoteRead)
def refresh_note(payload) -> NoteRead:
    return service.update(payload)
