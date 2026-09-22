"""Admin ``access`` (grants) router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): managing who holds which
permission is itself a privileged action. Exposed as ``module`` so the kernel's
entry-point discovery mounts it at ``/api/v1/access`` with no composition-root
edit. Modules then gate their own actions with ``require_permission`` against the
grants administered here.

A grant names a permission the app **declares** (see :func:`_refuse_undeclared`), the
same check ``terp grant add`` has made since ADR 0089. Revocation deliberately makes no
such check: it is by grant id here, and a permission the app has since stopped declaring
is exactly the stale grant that most needs removing.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from terp.core import (
    ControlPlane,
    ErrorDetail,
    ModuleAccess,
    build_access_model,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    Roles,
    SessionDep,
    ValidationFailedError,
    operation,
)

from terp.capabilities.access.expansion import subject_refs_for
from terp.capabilities.access.module_roles import (
    ModuleRoleService,
    validate_assignment,
)
from terp.capabilities.access.operations import (
    ACCESS_ASSIGN_MODULE_ROLE,
    ACCESS_CREATE_GRANT,
    ACCESS_DELETE_GRANT,
    ACCESS_GET_MODEL,
    ACCESS_GET_SUBJECT,
    ACCESS_LIST_GRANTS,
    ACCESS_REVOKE_MODULE_ROLE,
)
from terp.capabilities.access.schemas import (
    AccessModelRead,
    GrantCreate,
    GrantRead,
    HeldModuleRoleRead,
    HeldPermissionRead,
    ModuleRoleAssign,
    ModuleRoleRead,
    SubjectAccessRead,
    SubjectRefRead,
)
from terp.capabilities.access.service import AccessService

router = APIRouter(tags=["access"])
_service = AccessService()
_module_roles = ModuleRoleService()


def _declarations(request: Request) -> tuple[ControlPlane, tuple[ModuleSpec, ...]]:
    """The app's own control plane and mounted specs, or a refusal.

    Fails closed rather than guessing. Every real mount has both — ``create_app`` records
    them on ``app.state`` — so the only caller that can reach the refusal is a hand-composed
    app, and for a *write* path guessing on its behalf is how an unenforceable row gets
    stored. Shared by the projection, the provenance view and the writer, so the three cannot
    disagree about what counts as a composed app — the provenance view had its own third copy
    of this block until a coverage gap pointed at it, which is exactly the drift a shared
    helper is for. :func:`_refuse_undeclared` keeps its own lookup deliberately: it needs no
    specs, and its refusal names the field it came from so a form can attach it.
    """
    plane = getattr(request.app.state, "terp_control_plane", None)
    specs = getattr(request.app.state, "terp_module_specs", None)
    if plane is None or specs is None:
        raise ValidationFailedError(
            "this app exposes no control plane, so its authority surface cannot be "
            "projected; compose it with create_app",
            details=(ErrorDetail(code="no_control_plane"),),
        )
    return plane, specs


def _refuse_undeclared(request: Request, permission: str) -> None:
    """Refuse *permission* unless the app declares it, and say what it does declare.

    ``terp grant add`` has validated against the app's own control plane since ADR 0089,
    for a reason that applies just as much here: a grant of a string the app never checks
    is not a lenient grant, it is a silent no-op, and whoever wrote it will believe the
    subject is authorized until the moment it is not. The HTTP path skipped the check, so
    the two write paths disagreed about the same table — the CLI refused a typo and the
    endpoint stored it.

    The catalog comes back in ``details`` rather than only in the prose, which is the one
    thing this can do that the command cannot: the caller is a permission editor, and a
    machine-readable list of the valid choices is what lets it offer them instead of
    asking someone to retype the name.

    Fails closed when the app exposes no control plane, exactly as the command does. Every
    real mount has one — ``create_app`` records it on ``app.state`` — so the only caller
    that can see this is a hand-composed app, and guessing on its behalf is the one
    outcome that could store an unenforceable grant.
    """
    plane = getattr(request.app.state, "terp_control_plane", None)
    if plane is None:
        raise ValidationFailedError(
            "this app exposes no control plane, so the permission cannot be checked "
            "against what it declares; grants are refused rather than stored unverified",
            details=(ErrorDetail(code="no_control_plane", loc="permission"),),
        )
    catalog = {p.name: p.min_role.name for p in plane.permissions.permissions}
    if permission in catalog:
        return
    raise ValidationFailedError(
        f"this app does not declare a permission named {permission!r}. A grant of a "
        "permission nothing checks is a silent no-op, so it is refused rather than "
        "stored; the permissions this app does declare are listed in the details.",
        details=(
            ErrorDetail(
                code="undeclared_permission", loc="permission", msg=permission
            ),
            *(
                ErrorDetail(
                    code="declared_permission",
                    loc=name,
                    msg=f"needs role {min_role} or higher",
                )
                for name, min_role in sorted(catalog.items())
            ),
        ),
    )


@router.get("/model", response_model=AccessModelRead)
@operation(ACCESS_GET_MODEL)
def get_access_model(request: Request) -> AccessModelRead:
    """The declared authority surface: the ladder, the permissions, and every module.

    The read half of a permission editor, and the reason the projection it is built on moved
    into the kernel: this capability cannot import ``terp.cli``, where ``terp inspect access``
    lives. One builder, so the pane and the audit view cannot disagree about who may do what.

    Derivation over what ``create_app`` recorded on ``app.state`` — no database read at all,
    which is why it says nothing about *who holds* anything. That question needs the grant
    rows and is a different endpoint.

    Admin-only, through this module's own ``Policy``. The permission topology is a map of
    where the doors are, so it is not something an under-privileged caller should be able to
    enumerate; a caller asking what *they themselves* may do is answered by ``GET /me``
    (ADR 0096), which needs no privilege because it only ever reports the caller's own.
    """
    plane, specs = _declarations(request)
    return AccessModelRead.model_validate(build_access_model(plane, specs))


@router.get("/subjects/{subject_id}", response_model=SubjectAccessRead)
@operation(ACCESS_GET_SUBJECT)
def get_subject_access(
    subject_id: uuid.UUID, request: Request, session: SessionDep
) -> SubjectAccessRead:
    """One subject's effective access, with the provenance of every right.

    "Why can this person do that?" is the question an administrator has to be able to answer
    before any of this is safe, and it is the one a matrix of effective answers cannot answer
    on its own. Every row here names the subject it came from — the person themselves, or a
    group they belong to — because a right whose origin is unknown is a right nobody can
    remove with confidence.

    Two things are reported rather than filtered. A grant naming a permission the app no
    longer declares comes back with ``declared: false``, and a module role at an undeclared
    rank or in a module that no longer accepts them comes back with its reason in ``stale`` —
    on the reasoning ``terp grant list`` gives, that a filtered row is a right nobody can
    explain. And where several module rows exist for one module, only the highest is marked
    ``effective``, which is the thing most often misread: assigning a lower rung alongside a
    higher one changes nothing at all.
    """
    plane, specs = _declarations(request)

    refs = subject_refs_for(session, subject_id)
    by_id = {ref.id: ref for ref in refs}
    declared_permissions = {p.name: p for p in plane.permissions.permissions}
    ranks = {role.rank: role.name for role in plane.permissions.roles}
    assignable = {
        spec.name
        for spec in specs
        if spec.access is not None and spec.access.assignable
    }

    def _ref(holder: uuid.UUID) -> SubjectRefRead:
        ref = by_id.get(holder)
        if ref is None:  # pragma: no cover - holders come from the expanded set itself
            return SubjectRefRead(id=holder, kind="subject", name=None)
        return SubjectRefRead(id=ref.id, kind=ref.kind, name=ref.name)

    held = _service.held_with_subjects(session, set(by_id))
    permissions = [
        HeldPermissionRead(
            name=name,
            label=(
                declared_permissions[name].label or None
                if name in declared_permissions
                else None
            ),
            declared=name in declared_permissions,
            via=_ref(holder),
        )
        for name, holder in sorted(held, key=lambda row: (row[0], str(row[1])))
    ]

    assignments = _module_roles.held_with_subjects(session, set(by_id))
    winning = {}
    for module, rank, _holder in assignments:
        # Sentinel-free, and this one was a crash rather than a wrong answer: with a `-1`
        # default a stored rank of -1 never won, `winning` stayed empty, and the lookup below
        # raised `KeyError` — a 500 from the endpoint whose job is explaining a right.
        current = winning.get(module)
        if current is None or rank > current:
            winning[module] = rank
    module_roles = []
    for module, rank, holder in sorted(
        assignments, key=lambda row: (row[0], -row[1], str(row[2]))
    ):
        stale = []
        if rank not in ranks:
            stale.append("this app no longer declares a role at this rank")
        if module not in assignable:
            stale.append("this app no longer declares the module assignable")
        module_roles.append(
            HeldModuleRoleRead(
                module=module,
                role_rank=rank,
                role=ranks.get(rank),
                effective=winning[module] == rank,
                stale=stale,
                via=_ref(holder),
            )
        )

    return SubjectAccessRead(
        subject_id=subject_id,
        via=[
            SubjectRefRead(id=ref.id, kind=ref.kind, name=ref.name) for ref in refs
        ],
        permissions=permissions,
        module_roles=module_roles,
    )


@router.get("/grants", response_model=Page[GrantRead])
@operation(ACCESS_LIST_GRANTS)
def list_grants(
    subject_id: uuid.UUID, session: SessionDep, pagination: PaginationDep
) -> Page[GrantRead]:
    rows, total = _service.list_for(
        session, subject_id, skip=pagination.skip, limit=pagination.limit
    )
    return Page[GrantRead].of(
        [GrantRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/grants", response_model=GrantRead, status_code=201)
@operation(ACCESS_CREATE_GRANT)
def create_grant(
    payload: GrantCreate, request: Request, session: SessionDep
) -> GrantRead:
    _refuse_undeclared(request, payload.permission)
    return GrantRead.model_validate(
        _service.grant(session, payload.subject_id, payload.permission)
    )


@router.delete("/grants/{grant_id}", status_code=204)
@operation(ACCESS_DELETE_GRANT)
def delete_grant(grant_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, grant_id)


@router.put(
    "/subjects/{subject_id}/module-roles/{module}", response_model=ModuleRoleRead
)
@operation(ACCESS_ASSIGN_MODULE_ROLE)
def assign_module_role(
    subject_id: uuid.UUID,
    module: str,
    payload: ModuleRoleAssign,
    request: Request,
    session: SessionDep,
) -> ModuleRoleRead:
    # ``PUT``, not ``POST``: the pair in the path is the fact's identity, the table's unique
    # constraint says a subject holds at most one rung per module, and ``assign`` is already
    # idempotent on that pair. A ``POST`` that silently updates an existing row would be a
    # create that is not one, and would leave the caller no way to say "make it so" without
    # first reading whether a row exists.
    plane, specs = _declarations(request)
    validate_assignment(plane, specs, module, payload.role_rank)
    return ModuleRoleRead.model_validate(
        _module_roles.assign(session, subject_id, module, payload.role_rank)
    )


@router.delete("/subjects/{subject_id}/module-roles/{module}", status_code=204)
@operation(ACCESS_REVOKE_MODULE_ROLE)
def revoke_module_role(
    subject_id: uuid.UUID, module: str, session: SessionDep
) -> None:
    # Validates nothing, and returns 204 whether or not a row was there. A module the app has
    # stopped declaring assignable is exactly the assignment that most needs clearing, so
    # checking the catalog here would make it unreachable — the same reason
    # ``terp grant revoke`` does not check its own. And a 404 for "already absent" would make
    # a retry of a successful revoke look like a failure.
    _module_roles.revoke(session, subject_id, module)


module = ModuleSpec(
    name="access",
    router=router,
    access=ModuleAccess.platform_only(
        reason="administering grants is the authority that hands out every other authority; a per-module admin here would be a way around the ladder",
    ),
    policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
)
