# The same absence on the filter side: a declared filter that no endpoint
# forwards describes a narrowing the API cannot perform. The list is always
# unnarrowed, which is also the shape a reader is most likely to mistake for a
# permission problem rather than a missing parameter.
def list_notes(session, sort=None):
    return service.list(session, sort=sort)
