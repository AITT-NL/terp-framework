from terp.core import BaseSchema

from .models import Note


def provenance(note: Note) -> dict:
    """Reading the stamp is not forging it.

    Rendering who made a row is the point of keeping the trail. A rule justified
    by forgery must not refuse this, or it refuses the thing it protects.
    """
    return {"created_by": note.created_by_id, "modified_by": note.modified_by_id}
