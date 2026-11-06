def create_note(note, actor):
    note.created_by_id = actor.id
    note.modified_by_id = actor.id
