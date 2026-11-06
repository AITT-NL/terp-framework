def run(note_id):
    return text(f'SELECT * FROM notes WHERE id={note_id}')
