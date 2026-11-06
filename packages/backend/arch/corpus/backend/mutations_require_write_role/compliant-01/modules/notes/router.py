@router.post('/', response_model=NoteRead)
def create_note(payload) -> NoteRead:
    return NoteRead()
