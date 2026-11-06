from control_plane.jobs import NOTES_REINDEX


def request_reindex(session, note_id):
    enqueue(session, job=NOTES_REINDEX, payload={"note_id": note_id})
