@router.get('/', response_model=list[NoteRead])
def list_notes() -> list[NoteRead]:
    return []
