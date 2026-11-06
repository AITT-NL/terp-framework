# Two sorts are declared and no endpoint forwards one, so the read is never
# ordered by anything a caller asked for. Nothing here is wrong and nothing
# fails: a client generated from this contract simply has no way to sort, and a
# screen built on it ships with every column's sorting disabled.
def list_notes(session, author_id=None):
    return service.list(session, filters={"author_id": author_id})
