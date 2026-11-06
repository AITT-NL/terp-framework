# The mapping is built rather than written out, and that is still compliant: the
# rule judges whether the module forwards a filters mapping at all, never which
# names the mapping happens to contain. A computed mapping hides its names from a
# reader of the source; it does not hide its existence.
def list_notes(session, **query):
    return service.list(session, filters=_requested_filters(query), sort=query.get("sort"))
