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

    def production_problems(self) -> list[str]:
        """Reasons this control plane is unsafe to boot in production.

        There is exactly one today, and it is the promise this aggregate makes on its
        own field. ``job_system_actor_id`` is documented as the stand-in actor a job runs
        as when no user originated it, *so that a job's writes are never silently
        unstamped* — in :func:`terp.core.create_app`, again in
        :mod:`terp.core.scheduling` for a schedule, and a third time in ``terp guide
        jobs``. The field is optional and defaults to ``None``, so an app that declares a
        job or a schedule and never sets it passes every other boot check and then writes
        rows whose ``created_by_id`` answers **nobody** — the one answer a provenance
        column must not give, and one no unit test catches, because an unattributed row
        is still a row.

        Reported here rather than refused in :meth:`validation_errors`, and rather than
        papered over with a reserved sentinel actor. Development and test deliberately
        run without a system principal and keep booting (``create_app`` warns instead);
        production writing unattributable rows is the case the promise was made for. A
        sentinel default was the other candidate and is worse: the column is FK-less, so
        a constant would store fine and resolve to no principal anywhere, turning "no
        actor" into "an actor that cannot be looked up" — the same defect, harder to
        see. Mirrors :meth:`~terp.core.SecurityConfig.production_problems` and
        :meth:`~terp.core.PasswordPolicy.production_problems`.
        """
        if self.job_system_actor_id is not None:
            return []
        declared = len(self.jobs.jobs) + len(self.schedules.schedules)
        if declared == 0:
            return []
        subject = "declaration" if declared == 1 else "declarations"
        return [
            f"the control plane carries {declared} background {subject} (jobs and "
            "schedules) and no job_system_actor_id, so every write a job makes is "
            "stamped with no actor at all; pass "
            "ControlPlane(job_system_actor_id=<the app's system principal>) so the "
            "provenance trail names something, or drop the declarations if this app "
            "runs no background work"
        ]

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