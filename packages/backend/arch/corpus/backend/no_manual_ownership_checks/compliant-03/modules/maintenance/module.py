from terp.core import ModuleSpec

from .jobs import PURGE


module = ModuleSpec(name="maintenance", jobs=(PURGE,))
