# A filter mapping built elsewhere, and a computed name, are not statically
# knowable. Neither is judged: a guess there would reject correct code.
def list_notes(session, chosen, prepared):
    service.list(session, filters=prepared)
    return service.list(session, filters={chosen: 1})
