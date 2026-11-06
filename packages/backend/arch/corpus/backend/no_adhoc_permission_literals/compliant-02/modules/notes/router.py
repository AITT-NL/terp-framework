from app.control_plane.permissions import NOTES_DELETE


def remove_note(principal):
    require_permission(NOTES_DELETE, principal)
