@router.get('/', response_model=Page[NoteRead])
def list_notes() -> Page[NoteRead]:
    return Page()
@router.get('/{x}', response_model=NoteRead)
def get_note(x) -> NoteRead:
    return NoteRead()
