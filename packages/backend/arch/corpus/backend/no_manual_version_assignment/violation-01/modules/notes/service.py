def apply(db_obj, data):
    db_obj.version = data.version
    return db_obj
