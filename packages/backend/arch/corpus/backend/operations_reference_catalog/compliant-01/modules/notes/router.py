from control_plane.operations import NOTES_DELETE
from terp.core import operation


@router.delete('/{note_id}', status_code=204)
@operation(NOTES_DELETE)
def delete_note(note_id, session) -> None:
    _service.delete(session, note_id)


# A route with no declared operation at all is not this rule's concern -- an
# absent declaration is coverage's question (backend/routes_declare_operation),
# not a drifted one.
@router.get('/{note_id}')
def get_note(note_id, session):
    return _service.get(session, note_id)
