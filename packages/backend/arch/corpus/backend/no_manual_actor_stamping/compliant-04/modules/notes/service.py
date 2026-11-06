from .models import Note


def is_unstamped(note: Note) -> bool:
    """A comparison against a literal is a presence test, not a decision.

    No principal is named, so nothing is being decided about who may do what, and
    nothing is being written. This is the shape a careful reader concluded the
    rule refused, which is why it is contracted here rather than left to the
    detector's discretion.
    """
    return note.created_by_id is None
