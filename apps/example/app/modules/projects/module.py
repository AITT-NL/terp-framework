"""``projects`` manifest — a tenant-scoped example resource.

``Policy.default()`` gives secure-by-default authz (VIEWER reads, EDITOR writes).
The tenant isolation this module relies on is composed at the root via
``create_app(middleware=[Middleware(TenantMiddleware, ...)])`` (ADR 0021), so the
module declares no middleware itself.
"""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from app.modules.projects.router import router
from app.modules.projects.service import ProjectService

module = ModuleSpec(
    name="projects",
    router=router,
    services=(ProjectService,),
    policy=Policy.default(),
)
