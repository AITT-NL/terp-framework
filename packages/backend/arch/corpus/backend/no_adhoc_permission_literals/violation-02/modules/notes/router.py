def delete_note(principal):
    require_permission('notes:delete', principal)
