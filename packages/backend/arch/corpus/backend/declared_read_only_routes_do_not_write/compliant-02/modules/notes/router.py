@router.post('/preview', response_model=NotePreview)
@read_only
def preview_import(payload) -> NotePreview:
    existing = service.list(skip=0, limit=10)
    return NotePreview(rows=payload.rows, existing=existing)
@router.post('/', response_model=NoteRead)
def create_note(payload) -> NoteRead:
    return service.create(payload)
