from terp.core import TenantScopedService


class ProjectService(TenantScopedService):
    model = Project
