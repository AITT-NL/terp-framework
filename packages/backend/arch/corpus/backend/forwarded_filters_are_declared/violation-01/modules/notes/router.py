# "created_form" matches no declared filter, so it never narrows the read — and
# stays silent for every request that omits the parameter.
def list_notes(session, author_id=None, created_from=None):
    return service.list(
        session,
        filters={"author_id": author_id, "created_form": created_from},
    )
