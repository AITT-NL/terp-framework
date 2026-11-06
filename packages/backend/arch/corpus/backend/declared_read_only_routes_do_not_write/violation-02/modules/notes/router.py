@router.post('/preview', response_model=NotePreview)
@core.read_only
def preview_import(payload) -> NotePreview:
    service._save(payload)
    return NotePreview(rows=payload.rows)
