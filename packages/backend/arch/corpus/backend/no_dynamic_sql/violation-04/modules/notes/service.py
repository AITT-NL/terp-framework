"""Violation: SQL built into a variable (multiline %-format) and passed to text().

Deliberately session-free: the case must trigger only ``no_dynamic_sql`` (a
``session.execute(text(...))`` receiver would additionally trip the
``mutations_emit_audit`` smuggled-DML detection -- a different rule's concern).
"""

from sqlalchemy import text


def build_search(term):
    query = (
        "SELECT id FROM notes "
        "WHERE title LIKE '%%%s%%'" % term
    )
    return text(query)
