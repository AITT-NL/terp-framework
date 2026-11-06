def apply(db_obj, data):
    setattr(db_obj, "version", data.version)
    return db_obj
