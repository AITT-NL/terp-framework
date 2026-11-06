@router.api_route('/sync', methods=['GET', 'POST'])
def sync_notes(payload):
    return store._remove(payload)
