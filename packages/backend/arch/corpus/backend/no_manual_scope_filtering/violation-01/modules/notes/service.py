def visible_notes(session):
    return session.exec(select(Note).where(Note.deleted_at == None))  # noqa: E711
