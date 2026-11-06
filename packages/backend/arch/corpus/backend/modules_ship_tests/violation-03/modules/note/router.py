@router.get('/', response_model=Page[NoteRead])
def list_note() -> Page[NoteRead]:
    return Page()
