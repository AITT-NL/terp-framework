"""Permission profiles — named access models that compile to Terp primitives.

A profile is a **preset, never a new mechanism**: choosing one only decides which
existing, enforced primitives the scaffold composes — ``Policy`` for module /
endpoint access, model traits (``OwnedMixin`` / ``TenantScopedMixin``) for the
data layer, and the matching service base. The result is ordinary Terp code the
architecture gate checks like any hand-written module, and the access graph
(``terp inspect access``) renders exactly what was generated — the profile is
the UX layer; the typed declarations remain the enforceable contract.

Profiles are deliberately few and composable-by-name (a Studio can present them
as answers to "who can see / edit these records?"):

- ``shared``          authenticated app-wide rows; read VIEWER, write EDITOR
- ``role-gated``      like ``shared`` but mutations require ADMIN
- ``owner-private``   the creator owns each row; only the owner may update/delete
- ``tenant-private``  rows are isolated per tenant (reads filtered, writes stamped)
- ``tenant-owner``    tenant isolation + per-row owner write gate

Anything richer (a named ``Permission`` grant, a team/ACL predicate) starts from
one of these and layers the existing seams on top — see ``terp guide access``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleProfile:
    """One named permission profile the scaffold can compile to primitives."""

    name: str
    summary: str
    #: names imported from ``terp.core`` in the generated ``module.py``
    policy_imports: tuple[str, ...]
    #: the ``Policy`` expression placed on the generated ``ModuleSpec``
    policy_expr: str
    #: extra ``terp.core`` names mixed into the generated table model
    core_model_mixins: tuple[str, ...] = ()
    #: extra import lines for the generated ``models.py`` (capability mixins)
    model_import_lines: tuple[str, ...] = ()
    #: extra class names (from *model_import_lines*) mixed into the model
    capability_model_mixins: tuple[str, ...] = ()
    #: the service base class name for the generated ``service.py``
    service_base: str = "BaseService"
    #: the import line providing *service_base*
    service_import_line: str = "from terp.core import BaseService"
    #: extra scaffold follow-up notes (wiring the profile depends on)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def model_mixins(self) -> tuple[str, ...]:
        """Every mixin the generated model composes, in declaration order."""
        return self.core_model_mixins + self.capability_model_mixins


PROFILES: dict[str, ModuleProfile] = {
    "shared": ModuleProfile(
        name="shared",
        summary="Authenticated shared workspace: read VIEWER, write EDITOR (Policy.default()).",
        policy_imports=("ModuleSpec", "Policy"),
        policy_expr="Policy.default()",
    ),
    "role-gated": ModuleProfile(
        name="role-gated",
        summary="Reads for every authenticated VIEWER; mutations require ADMIN.",
        policy_imports=("ADMIN", "VIEWER", "ModuleSpec", "Policy"),
        policy_expr="Policy(read=VIEWER, write=ADMIN)",
    ),
    "owner-private": ModuleProfile(
        name="owner-private",
        summary=(
            "The creator owns each row: BaseService stamps owner_id on create and "
            "refuses a non-owner update/delete (OwnedMixin, ADR 0029)."
        ),
        policy_imports=("ModuleSpec", "Policy"),
        policy_expr="Policy.default()",
        core_model_mixins=("OwnedMixin",),
        notes=(
            "OwnedMixin gates writes only; to also hide other owners' rows from reads,"
            " register a scope predicate (terp guide ownership).",
        ),
    ),
    "tenant-private": ModuleProfile(
        name="tenant-private",
        summary=(
            "Rows are isolated per tenant: every read is filtered to the current "
            "tenant and create stamps tenant_id (TenantScopedMixin + TenantScopedService)."
        ),
        policy_imports=("ModuleSpec", "Policy"),
        policy_expr="Policy.default()",
        model_import_lines=("from terp.capabilities.tenancy import TenantScopedMixin",),
        capability_model_mixins=("TenantScopedMixin",),
        service_base="TenantScopedService",
        service_import_line="from terp.capabilities.tenancy import TenantScopedService",
        notes=(
            "Wire the tenant context at the composition root:"
            " create_app(..., middleware=[Middleware(TenantMiddleware, ...)])"
            " (terp guide tenancy).",
        ),
    ),
    "tenant-owner": ModuleProfile(
        name="tenant-owner",
        summary=(
            "Tenant isolation plus a per-row owner write gate: reads are tenant-"
            "filtered, and only a row's owner may update/delete it."
        ),
        policy_imports=("ModuleSpec", "Policy"),
        policy_expr="Policy.default()",
        core_model_mixins=("OwnedMixin",),
        model_import_lines=("from terp.capabilities.tenancy import TenantScopedMixin",),
        capability_model_mixins=("TenantScopedMixin",),
        service_base="TenantScopedService",
        service_import_line="from terp.capabilities.tenancy import TenantScopedService",
        notes=(
            "Wire the tenant context at the composition root (terp guide tenancy).",
            "OwnedMixin gates writes only; register a scope predicate for owner-"
            "filtered reads (terp guide ownership).",
        ),
    ),
}

DEFAULT_PROFILE = "shared"


def profile_names() -> tuple[str, ...]:
    """Every profile name, sorted — the CLI ``choices`` source of truth."""
    return tuple(sorted(PROFILES))


def get_profile(name: str) -> ModuleProfile:
    """Resolve *name* to a profile, failing closed with the valid choices."""
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(
            f"unknown profile {name!r}: choose one of {', '.join(profile_names())}"
        ) from None


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILES",
    "ModuleProfile",
    "get_profile",
    "profile_names",
]
