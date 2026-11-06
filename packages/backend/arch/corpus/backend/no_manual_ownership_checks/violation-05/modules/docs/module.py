from terp.core import ModuleSpec

from .service import DocService


module = ModuleSpec(name="docs", services=(DocService,))
