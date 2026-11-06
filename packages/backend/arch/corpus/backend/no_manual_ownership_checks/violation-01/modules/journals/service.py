def guard(entry, principal):
    if entry.owner_id != principal.id:
        raise PermissionDeniedError()
