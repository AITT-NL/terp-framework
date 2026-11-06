from terp.core import ModuleSpec

from .jobs import PURGE_EXPIRED_NOTES
from .service import NoteService


module = ModuleSpec(
    name="notes",
    services=(NoteService,),
    jobs=(PURGE_EXPIRED_NOTES,),
)
