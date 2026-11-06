# Both declarations are reachable: the endpoint exposes a parameter for each and
# forwards it, so what the read layer says is narrowable and orderable is.
def list_notes(session, author_id=None, sort=None):
    return service.list(
        session,
        filters={"author_id": author_id},
        sort=sort,
    )
