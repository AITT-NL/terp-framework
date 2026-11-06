def import_note(note, source_row, actor):
    note.title = source_row["title"]
    note.created_by_id = actor.id
    return note
