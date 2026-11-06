def list_notes(session, skip):
    return session.exec(
        select(Note).order_by(Note.created_at).offset(skip).limit(20)
    ).all()
