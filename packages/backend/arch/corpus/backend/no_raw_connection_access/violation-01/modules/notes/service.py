def purge(session):
    session.connection().execute('DELETE FROM notes')
