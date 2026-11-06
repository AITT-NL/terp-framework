def list_notes(session, skip):
    return session.exec(select(Note).offset(skip).limit(20)).all()
