def purge_note(note_id):
    return None


router.add_api_route("/{note_id}", purge_note, methods=["DELETE"])
