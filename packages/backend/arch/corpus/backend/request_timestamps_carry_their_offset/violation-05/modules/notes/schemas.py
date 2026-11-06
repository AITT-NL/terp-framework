import importlib

import terp.core

# The boundary's own module is the framework's to change, however an app reaches for it: by a
# literal attribute name, or by the module's dotted name.
REFUSED = getattr(terp.core, "timestamps").OFFSET_REQUIRED
BOUNDARY = importlib.import_module("terp.core.timestamps")
