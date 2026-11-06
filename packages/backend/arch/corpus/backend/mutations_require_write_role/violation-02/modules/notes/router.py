def create_note(payload) -> NoteRead:
    return NoteRead()


router.add_api_route("/", create_note, methods=["POST"])
