from terp.core import OperationDefinition, operation


@router.delete('/{note_id}', status_code=204)
@operation("notes.delete")
def delete_note(note_id, session) -> None:
    _service.delete(session, note_id)


@router.get('/{note_id}')
@operation(OperationDefinition(id="notes.get", label="View a note"))
def get_note(note_id, session):
    return _service.get(session, note_id)
