@router.get('/', response_model=Page[NoteRead])
def list_notes() -> Page[NoteRead]:
    return service.list()
@router.post('/', response_model=NoteRead)
def create_note(payload) -> NoteRead:
    return service.create(payload)
