def partition(notes, current_tenant):
    mine = []
    for note in notes:
        holder = note
        if holder.tenant_id == current_tenant:
            mine.append(note)
    return mine
