from sqlmodel import select


def entries_for(session, principal):
    return session.exec(
        select(Journal).where(
            Journal.owner_id == principal.id,
        )
    ).all()
