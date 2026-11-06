# No control_plane/operations.py at all: this app has not opted into operation
# coverage (the default), so an undeclared route is not this rule's concern.
@router.get('/')
def list_notes():
    return notes
