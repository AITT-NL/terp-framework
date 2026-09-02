"""The app-level control plane: one validated authority map per application."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from terp.core.audit import AuditPolicy
from terp.core.events import EventCatalog
from terp.core.jobs import JobCatalog
from terp.core.module_spec import ModuleSpec
from terp.core.operations import OperationCatalog
from terp.core.passwords import PasswordPolicy
from terp.core.permissions import PermissionModel
from terp.core.scheduling import ScheduleCatalog
from terp.core.security import SecurityConfig


@dataclass(frozen=True)
class ControlPlane:
    """Central authority configuration consumed by ``create_app``.

    Permissions, security, audit, the event catalog, and the job catalog are the
    registries wired into the runtime path today. Realtime and database registries
    attach to this aggregate in later slices.
    """

    permissions: PermissionModel = field(default_factory=PermissionModel.default)
    security: SecurityConfig = field(default_factory=SecurityConfig.default)
    audit: AuditPolicy = field(default_factory=AuditPolicy.default)
    events: EventCatalog = field(default_factory=EventCatalog.default)
    passwords: PasswordPolicy = field(default_factory=PasswordPolicy.default)
    jobs: JobCatalog = field(default_factory=JobCatalog.default)
    operations: OperationCatalog = field(default_factory=OperationCatalog.default)
    schedules: ScheduleCatalog = field(default_factory=ScheduleCatalog.default)
    job_system_actor_id: uuid.UUID | None = None

    @classmethod
    def default(cls) -> ControlPlane:
        """Compatibility control plane for existing apps."""
        return cls()

    def validation_errors(self, specs: Sequence[ModuleSpec]) -> tuple[str, ...]:
        """Return every control-plane reference error in *specs*."""
        errors: list[str] = []
        for spec in specs:
            errors.extend(self._policy_errors(spec))
            errors.extend(self._event_errors(spec))
            errors.extend(self._job_errors(spec))
            errors.extend(self._permission_errors(spec))
        errors.extend(self._schedule_errors())
        return tuple(errors)

    def _policy_errors(self, spec: ModuleSpec) -> list[str]:
        """Policy references must resolve to the declared role/permission, by value.

        Two different failures, reported differently because the fix differs. An
        *undeclared* reference is a name the model does not register. A *shadow* is a name
        it does register, cited with a different rank floor — which boots clean, enforces
        the floor the policy carries, and is displayed everywhere as the floor that was
        declared.
        """
        if spec.policy is None or spec.policy.is_public:
            return []
        requirements = (spec.policy.read_requirement, spec.policy.write_requirement)
        errors = [
            f"module {spec.name!r} policy references undeclared {requirement.label!r}"
            for requirement in self.permissions.missing_requirements(requirements)
        ]
        # Deduplicated because a policy very commonly cites the same authority for both
        # reads and writes, and this message is long enough that saying it twice in one
        # semicolon-joined BootError buries the second half of the error.
        shadowed = dict.fromkeys(self.permissions.shadowed_requirements(requirements))
        errors.extend(
            f"module {spec.name!r} policy cites {requirement.label!r} with rank floor "
            f"{requirement.min_rank}, but the control plane declares it at "
            f"{self.permissions.declared_rank(requirement)}. At least one declared role "
            "sits between the two, so the policy admits or refuses someone the "
            "declaration does not — it would be enforced at the floor it carries while "
            "every view reports the declared one. Reference the declared object from the "
            "control plane rather than constructing another."
            for requirement in shadowed
        )
        return errors

    def _event_errors(self, spec: ModuleSpec) -> list[str]:
        """Every emitted/subscribed event must be the registered catalog entry (no drift)."""
        errors: list[str] = []
        for relation, definitions in (("emits", spec.emits), ("subscribes", spec.subscribes)):
            for definition in self.events.missing_events(definitions):
                errors.append(
                    f"module {spec.name!r} {relation} event {definition.name!r} "
                    "that is not registered in the events catalog; declare it or "
                    "reference the existing catalog constant"
                )
        return errors

    def _permission_errors(self, spec: ModuleSpec) -> list[str]:
        """Every permission a module claims must be the registered entry (no drift).

        The same guarantee, in the same words, that ``_event_errors`` and ``_job_errors``
        already make for their catalogs. Matched by value, so a module cannot claim
        ``notes.delete`` with a floor or a label the control plane does not declare and then
        have a permission editor render its version of the row.
        """
        return [
            f"module {spec.name!r} claims permission {permission.name!r} that is not "
            "registered in the control plane's PermissionModel, or is registered with a "
            "different minimum role or label; declare it there or reference the existing "
            "constant"
            for permission in self.permissions.missing_permissions(spec.permissions)
        ]

    def _job_errors(self, spec: ModuleSpec) -> list[str]:
        """Every declared job must be the registered catalog entry (no drift, like events)."""
        return [
            f"module {spec.name!r} declares job {definition.name!r} that is not "
            "registered in the jobs catalog; declare it or reference the existing "
            "catalog constant"
            for definition in self.jobs.missing_jobs(spec.jobs)
        ]

    def _schedule_errors(self) -> list[str]:
        """Every schedule must enqueue a job registered in the jobs catalog (no drift).

        The boot half of the scheduler seam: a :class:`~terp.core.ScheduleDefinition` carries
        a typed :class:`~terp.core.JobDefinition`, and that job must be the canonical catalog
        entry — so a schedule can never trigger a job the app does not declare (validated
        against the same :class:`~terp.core.JobCatalog`, by value, like the jobs check).
        """
        return [
            f"schedule {schedule.name!r} enqueues job {schedule.job.name!r} that is not "
            "registered in the jobs catalog; declare the job or reference the existing "
            "catalog constant"
            for schedule in self.schedules.missing_jobs(self.jobs)
        ]


__all__ = ["ControlPlane"]