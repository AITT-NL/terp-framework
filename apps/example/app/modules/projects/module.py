"""``projects`` manifest — a tenant-scoped example resource.

``Policy.default()`` gives secure-by-default authz (VIEWER reads, EDITOR writes).
The tenant isolation this module relies on is composed at the root via
``create_app(middleware=[Middleware(TenantMiddleware, ...)])`` (ADR 0021), so the
module declares no middleware itself.

``access`` opts it into **per-module roles** (ADR 0121), which is what makes this the
second such module in the app — and it is here rather than on an owner-scoped resource
for a reason that shows up in the pane. ``notes`` puts its delete behind a named
permission, so the ``admin`` rung there buys nothing an ``editor`` did not already have:
the delete needs a grant no rung confers. A plain CRUD resource has no such gate, so its
``editor`` rung really does hand over the delete. The two rows therefore *differ*, which
is the whole reason the pane shows the delta per rung instead of one table of tiers.
"""

from __future__ import annotations

from terp.core import ModuleAccess, ModuleSpec, Policy

from app.modules.projects.router import router
from app.modules.projects.service import ProjectService

module = ModuleSpec(
    name="projects",
    router=router,
    services=(ProjectService,),
    access=ModuleAccess(label="Projects", assignable=True),
    policy=Policy.default(),
)
