def request_reindex(session, note_id):
    enqueue(session, job="notes.reindex", payload={"note_id": note_id})
