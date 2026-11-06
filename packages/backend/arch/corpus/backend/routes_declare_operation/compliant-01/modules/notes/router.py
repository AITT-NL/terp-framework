from control_plane.operations import NOTES_LIST
from terp.core import operation


@router.get('/')
@operation(NOTES_LIST)
def list_notes():
    return notes
