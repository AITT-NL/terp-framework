def cleanup_notes(payload):
    return service.delete(payload)


router.add_api_route("/cleanup", cleanup_notes, methods=["GET"])
