from sqlalchemy.orm import Session


def note_count(session: Session) -> int:
    return len(session.exec(query).all())
