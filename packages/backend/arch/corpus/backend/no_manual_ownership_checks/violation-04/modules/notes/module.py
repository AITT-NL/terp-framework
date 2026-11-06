from terp.core import ModuleSpec

from .jobs import MODULE_JOBS
from .service import NoteService


module = ModuleSpec(
    name="notes",
    services=(NoteService,),
    jobs=MODULE_JOBS,
)
