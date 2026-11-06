@router.get('/', response_model=Page[NoteRead])
def list_notes() -> Page[NoteRead]:
    return Page()
