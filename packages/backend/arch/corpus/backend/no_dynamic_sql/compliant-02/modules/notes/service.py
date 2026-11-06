"""Compliant near-misses: static SQL that merely LOOKS dynamic must stay clean.

* adjacent string literals merge into one static literal at parse time — that is
  juxtaposition, not concatenation;
* a comment or a plain string mentioning ``text(f"...")`` is not a call;
* parameters bind data without building SQL.
"""

from sqlalchemy import text

# text(f"SELECT * FROM notes WHERE id={note_id}") in a comment must not fire.
GUIDE = 'never call text(f"SELECT ...") — bind parameters instead'


def fetch(session, note_id):
    stmt = text(
        "SELECT id, title FROM notes "
        "WHERE id = :id AND deleted_at IS NULL"
    )
    return session.execute(stmt, {"id": note_id})
