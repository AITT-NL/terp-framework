def archive_note(session, note):
    note.archived = True
    session.add(note)
    session.commit()
