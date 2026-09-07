"""Per-module role assignment — the service, and the resolver the kernel guard calls.

The write half of ADR 0121: who holds which rung in which module. The declaration of what a
rung *means* stays in code and is never touched here, which is the whole division — this
module only ever records an assignment.

Two disciplines carried over from ``terp grant``, and both are load-bearing rather than tidy:

* **A write validates against the declaration and refuses.** An assignment naming a rank the
  app's ladder does not declare, a module that has not opted in, or a module that administers
  the platform's own authority, is not a lenient assignment — it is a row that can never fire,
  or worse, one that fires somewhere nobody intended. This is ADR 0089's "there is no
  ``--force``" applied to a second table.
* **A stale row is shown, not hidden.** If the app later drops a rung or stops declaring a
  module assignable, the stored assignment is exactly the thing an administrator needs to find
  and clean up. ``terp grant list`` marks such an entry rather than filtering it, and so does
  this; a filtered row is an unexplainable right.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, func, select

from terp.core import (
    AuditAction,
    BaseService,
    ControlPlane,
    ModuleSpec,
    ValidationFailedError,
    register_module_rank_projector,
)

from terp.capabilities.access.expansion import subject_ids_for
from terp.capabilities.access.models import ModuleRole
from terp.capabilities.access.schemas import ModuleRoleCreate, ModuleRoleUpdate


class ModuleRoleService(BaseService[ModuleRole, ModuleRoleCreate, ModuleRoleUpdate]):
    model = ModuleRole

    def _find(
        self, session: Session, subject_id: uuid.UUID, module: str
    ) -> ModuleRole | None:
        return session.exec(
            select(ModuleRole).where(
                ModuleRole.subject_id == subject_id, ModuleRole.module == module
            )
        ).first()

    def assign(
        self, session: Session, subject_id: uuid.UUID, module: str, role_rank: int
    ) -> ModuleRole:
        """Record that *subject_id* holds *role_rank* in *module*.

        Idempotent on the pair, because the unique constraint says a subject holds at most one
        rung per module: re-assigning the same rank returns the existing row untouched, and a
        different rank is an update of that one fact rather than a second row. Both paths go
        through the audited chokepoint, since a change to who may do what is exactly the kind
        of write the audit log exists for.
        """
        existing = self._find(session, subject_id, module)
        if existing is not None:
            if existing.role_rank == role_rank:
                return existing
            existing.role_rank = role_rank
            return self._save(session, existing, AuditAction.UPDATED)
        entity = ModuleRole(subject_id=subject_id, module=module, role_rank=role_rank)
        return self._save(session, entity, AuditAction.CREATED)

    def revoke(self, session: Session, subject_id: uuid.UUID, module: str) -> bool:
        """Remove *subject_id*'s rung in *module*; return whether one was removed.

        Deliberately validates nothing about the module. A module the app has since stopped
        declaring assignable is precisely the assignment you most need to be able to clear,
        and insisting it still qualifies would make it unreachable — the same reason
        ``terp grant revoke`` does not check its catalog.
        """
        existing = self._find(session, subject_id, module)
        if existing is None:
            return False
        self._remove(session, existing)
        return True

    def highest_rank(self, session: Session, subject_id: uuid.UUID, module: str) -> int:
        """The highest rank *subject_id* holds in *module* over the expanded subject set.

        ``0`` when there is none. Nothing forbids an app from declaring a rung at rank ``0``
        — ``Role`` validates its name and not its number — so this cannot claim to be below
        every declarable rung, and does not: it says "no rung", and a declared rank-``0`` rung
        reports identically. That costs nothing, because the value is only ever compared
        against a floor, and a rung at rank ``0`` clears exactly the floors that ``0``-as-absent
        already clears. What it does mean is that ``0`` is not a safe rank to give a rung any
        distinct meaning at, which is the honest thing to say rather than a range to promise.

        Expanded, so a rung assigned to a *group* reaches its members through the seam that
        already makes a group's grants reach them — which is what the FK-less ``subject_id``
        was for.

        One aggregate query rather than a fetch-and-max in Python: this is on the request path
        of every guarded route whose caller does not already clear the floor.
        """
        subjects = subject_ids_for(session, subject_id)
        highest = session.exec(
            select(func.max(ModuleRole.role_rank)).where(
                col(ModuleRole.subject_id).in_(subjects),
                ModuleRole.module == module,
            )
        ).one()
        return int(highest or 0)

    def held_with_subjects(
        self, session: Session, subject_ids: set[uuid.UUID]
    ) -> list[tuple[str, int, uuid.UUID]]:
        """Every assignment over *subject_ids*, as ``(module, rank, holder)``.

        Unlike :meth:`highest_rank` this keeps every row rather than collapsing to the winner,
        because an explanation has to be able to say that a rung came from a group even when a
        direct assignment also exists.
        """
        rows = session.exec(
            select(
                ModuleRole.module, ModuleRole.role_rank, ModuleRole.subject_id
            ).where(col(ModuleRole.subject_id).in_(subject_ids))
        ).all()
        return [(row[0], row[1], row[2]) for row in rows]

    def list_for(
        self, session: Session, subject_id: uuid.UUID, *, skip: int, limit: int
    ) -> tuple[list[ModuleRole], int]:
        """Paginated assignments naming *subject_id* directly (not the expanded set).

        The question this answers is "what has been assigned to this subject", which is a
        different question from "what does this subject effectively hold" — the latter needs
        the expansion and belongs to the view that explains provenance.
        """
        return self._paginate(
            session,
            self.base_query().where(ModuleRole.subject_id == subject_id),
            skip=skip,
            limit=limit,
        )


_service = ModuleRoleService()


def resolve_module_rank(
    session: Session, subject_id: uuid.UUID, module_name: str
) -> int:
    """Fill ``create_app(module_rank_resolver=…)`` — the kernel's per-module rank seam.

    The read-only counterpart of :meth:`ModuleRoleService.assign`, and the only thing the
    guard calls. The kernel never imports this capability; it is handed this callable, exactly
    as it is handed ``enforce_permission`` (ADR 0016 §1).
    """
    return _service.highest_rank(session, subject_id, module_name)


def assignable_modules(specs: tuple[ModuleSpec, ...]) -> dict[str, str]:
    """Every module that has opted into assignment, mapped to the label it declared.

    The writer's allowlist, and the reason a refusal can name what *is* assignable instead of
    only saying no. Built from the specs the app mounted rather than from a list this
    capability keeps, because a list here would be a second source of truth for something each
    module already answers.
    """
    return {
        spec.name: (spec.access.label or spec.name)
        for spec in specs
        if spec.access is not None and spec.access.assignable
    }


def validate_assignment(
    plane: ControlPlane, specs: tuple[ModuleSpec, ...], module: str, role_rank: int
) -> None:
    """Refuse an assignment the declarations do not support, naming what would be supported.

    Three separate refusals, because they have three different fixes:

    * a module that administers the platform's own authority is **never** assignable, and
      per-module ``admin`` there would be a way around the ladder rather than a use of it —
      ``admin`` in ``users`` provisions accounts, ``admin`` in ``access`` hands out every
      other authority;
    * a module that has simply not opted in has no per-module semantics at all, so a row
      naming it could never fire;
    * a rank the app's ladder does not declare cannot be compared against a policy floor in
      any meaningful way, and ``PermissionModel.role_for_rank`` already fails closed on one.
    """
    refusing = next(
        (
            spec
            for spec in specs
            if spec.name == module
            and spec.access is not None
            and spec.access.is_platform_only
        ),
        None,
    )
    if refusing is not None:
        raise ValidationFailedError(
            f"module {module!r} declares that it is never per-module assignable: "
            f"{refusing.access.platform_reason}"
        )

    allowed = assignable_modules(specs)
    if module not in allowed:
        raise ValidationFailedError(
            f"module {module!r} has not opted into per-module role assignment, so an "
            "assignment naming it could never take effect. The modules that have are: "
            f"{sorted(allowed) or '(none)'}."
        )

    ranks = {role.rank: role.name for role in plane.permissions.roles}
    if role_rank not in ranks:
        readable = ", ".join(
            f"{name} ({rank})" for rank, name in sorted(ranks.items())
        )
        raise ValidationFailedError(
            f"this app declares no role at rank {role_rank}, so an assignment at that rank "
            f"could not be compared against any policy. It declares: {readable}."
        )


def project_held_module_ranks(
    session: Session, subject_id: uuid.UUID
) -> dict[str, int]:
    """Every module rung *subject_id* holds, for the ``/me`` projection (ADR 0121).

    The display counterpart of :func:`resolve_module_rank`: the same expanded subject set, but
    every module at once instead of a yes/no for one. Registered below, so ``GET /me`` reports
    the rungs without the auth or identity capability importing this one — exactly how the
    grant projection already works.

    A **display** input, never a decision. The guard re-resolves on every request, and a client
    treating this as authority has moved the gate to the wrong side of the wire. Reporting a
    rung the caller holds cannot widen anything; what it fixes is the opposite failure, a
    packaged UI that hid a module the caller could actually reach.
    """
    held = _service.held_with_subjects(session, subject_ids_for(session, subject_id))
    highest: dict[str, int] = {}
    for module, rank, _holder in held:
        # Sentinel-free: `rank > highest.get(module, -1)` looked equivalent and was not, because
        # a stored rank of -1 or below never won. Ranks are app-declared integers and this must
        # not trust the table about their range.
        current = highest.get(module)
        if current is None or rank > current:
            highest[module] = rank
    return highest


# Registered at import, like the grant projector: an app that mounts this capability gets the
# rungs in `/me` without wiring it, and one that does not projects nothing.
register_module_rank_projector(project_held_module_ranks)


__all__ = [
    "ModuleRoleService",
    "assignable_modules",
    "project_held_module_ranks",
    "resolve_module_rank",
    "validate_assignment",
]
