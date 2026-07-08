"""``projects`` service — a tenant-scoped CRUD service.

Extends :class:`~terp.capabilities.tenancy.TenantScopedService`, which stamps
``tenant_id`` on create (through the audited ``BaseService`` chokepoint) and whose
reads are filtered by the registered tenant predicate. The
``tenant_scoped_models_use_scoped_service`` arch rule requires exactly this — a
tenant-scoped model may not be served by a plain ``BaseService`` (its inserts would
be unstamped and never visible).
"""

from __future__ import annotations

from terp.capabilities.tenancy import TenantScopedService

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectService(TenantScopedService[Project, ProjectCreate, ProjectUpdate]):
    model = Project
