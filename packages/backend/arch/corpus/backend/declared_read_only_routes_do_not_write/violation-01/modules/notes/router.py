@router.post('/validation', response_model=NoteVerdict)
@read_only
def validate_candidate(payload) -> NoteVerdict:
    return service.create(payload)
