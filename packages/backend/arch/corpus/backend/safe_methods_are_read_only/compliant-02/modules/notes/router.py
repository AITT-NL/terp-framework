@router.get('/stats', response_model=NoteStats)
def note_stats(filters):
    merged = {}
    merged.update(filters)
    return NoteStats(**merged)
