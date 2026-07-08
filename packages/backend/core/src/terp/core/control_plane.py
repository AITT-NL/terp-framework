"""The app-level control plane: one validated authority map per application."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from terp.core.audit import AuditPolicy
from terp.core.events import EventCatalog
from terp.core.jobs import JobCatalog
from terp.core.module_spec import ModuleSpec
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
        errors.extend(self._schedule_errors())
        return tuple(errors)

    def _policy_errors(self, spec: ModuleSpec) -> list[str]:
        """Policy references must resolve to a declared role/permission."""
        if spec.policy is None or spec.policy.is_public:
            return []
        missing = self.permissions.missing_requirements(
            (spec.policy.read_requirement, spec.policy.write_requirement)
        )
        return [
            f"module {spec.name!r} policy references undeclared {requirement.label!r}"
            for requirement in missing
        ]

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