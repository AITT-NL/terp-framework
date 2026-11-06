def list_notes(session, author_id=None, created_from=None):
    return service.list(
        session,
        filters={"author_id": author_id, "created_from": created_from},
    )
