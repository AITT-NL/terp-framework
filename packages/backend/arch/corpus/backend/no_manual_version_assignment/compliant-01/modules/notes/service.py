def apply(db_obj, data):
    # The concurrency token is left untouched; the persistence layer bumps it.
    db_obj.title = data.title
    token = db_obj.version
    return db_obj, token
