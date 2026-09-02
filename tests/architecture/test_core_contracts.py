"""Phase 1 gate (runtime): the ``terp.core`` public-surface + kernel contracts.

Complements the static checks in ``test_core_boundary.py``: these import the
real package and assert the public API is present, curated, and behaves as the
secure-by-default design requires.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlmodel import Field

import terp.core as core
from terp.core import (
    ADMIN,
    EDITOR,
    AppError,
    BaseTable,
    BaseUpdateSchema,
    ControlPlane,
    ModuleAccess,
    Permission,
    PermissionModel,
    ModuleSpec,
    NotFoundError,
    Policy,
    Role,
    Roles,
    VIEWER,
    build_error_envelope,
)


def test_public_surface_excludes_internal() -> None:
    assert "_internal" not in core.__all__
    assert not any("_internal" in name for name in core.__all__)
    for name in core.__all__:
        assert hasattr(core, name), f"terp.core.__all__ advertises missing name {name!r}"


def test_public_surface_is_sorted() -> None:
    assert list(core.__all__) == sorted(core.__all__)


def test_modulespec_importable_from_public_surface() -> None:
    # The literal Phase 1 gate: `from terp.core import ModuleSpec` works.
    from terp.core import ModuleSpec as _ModuleSpec

    assert _ModuleSpec is ModuleSpec


def test_roles_are_ordered() -> None:
    assert Roles.VIEWER < Roles.EDITOR < Roles.ADMIN


def test_policy_default_is_secure() -> None:
    policy = Policy.default()
    assert policy.authenticated is True
    assert policy.is_public is False
    assert policy.read_requirement.label == "role:viewer"
    assert policy.write_requirement.label == "role:editor"


def test_policy_accepts_typed_roles_and_permissions() -> None:
    billing_read = Permission("billing.read", min_role=VIEWER)
    billing_write = Permission("billing.write", min_role=Role("approver", rank=25))
    policy = Policy(read=billing_read, write=billing_write)
    assert policy.read_requirement.label == "permission:billing.read"
    assert policy.write_requirement.label == "permission:billing.write"


def test_permission_model_rejects_duplicate_authority() -> None:
    duplicate = Role("viewer", rank=11)
    with pytest.raises(ValueError, match="duplicate role"):
        PermissionModel(roles=[VIEWER, duplicate])


def test_control_plane_validates_policy_references() -> None:
    billing_read = Permission("billing.read", min_role=VIEWER)
    model = PermissionModel(permissions=[billing_read])
    plane = ControlPlane(permissions=model)
    ok = ModuleSpec(name="billing", policy=Policy(read=billing_read, write=VIEWER))
    assert plane.validation_errors([ok]) == ()

    missing = Permission("billing.write", min_role=VIEWER)
    bad = ModuleSpec(name="billing", policy=Policy(read=billing_read, write=missing))
    assert plane.validation_errors([bad]) == (
        "module 'billing' policy references undeclared 'permission:billing.write'",
    )


def test_module_access_is_absent_by_default_and_refuses_a_contradiction() -> None:
    """Secure by default through absence, and the invariants that keep a pane honest.

    A `ModuleSpec` with no `access` declaration does not take part in per-module assignment
    (ADR 0112) — which is today's behaviour, so a capability that never considered the
    question is safe by omission. Opting in requires a label as a *constructor* invariant
    rather than a coverage-gated one: the field is new and has no call sites to break, and a
    module cannot ask to appear in an editor and decline to say what it is called.
    """
    assert ModuleSpec(name="notes").access is None

    opted_in = ModuleAccess(label="Notes", summary="Free-form notes.", assignable=True)
    assert opted_in.is_platform_only is False

    refused = ModuleAccess.platform_only(reason="grants hand out every other authority")
    assert refused.is_platform_only is True
    assert refused.assignable is False

    with pytest.raises(ValueError, match="requires a label"):
        ModuleAccess(assignable=True)
    with pytest.raises(ValueError, match="non-empty justification"):
        ModuleAccess.platform_only(reason="   ")
    # Both at once is the contradiction that matters: it would put a module that administers
    # the platform's own authority into the editor as an assignable row.
    with pytest.raises(ValueError, match="both assignable and platform_only"):
        ModuleAccess(label="Users", assignable=True, platform_reason="also platform")


def test_the_platform_capabilities_refuse_per_module_assignment() -> None:
    """Per-module `admin` in the wrong module is a way around the ladder, not a use of it.

    `admin` in `users` provisions accounts and `admin` in `access` grants anything to
    anyone, so the four capabilities that administer the platform's own authority declare
    that they are never assignable — each with a reason, in the shape `Policy.public` uses
    for its own justified exception. Asserted here rather than in each capability's own
    tests because the property that matters is that *none* of them is missing.
    """
    from terp.capabilities.access.router import module as access_module
    from terp.capabilities.audit.router import module as audit_module
    from terp.capabilities.groups.router import module as groups_module
    from terp.capabilities.users.router import module as users_module

    for module in (users_module, groups_module, access_module, audit_module):
        assert module.access is not None, module.name
        assert module.access.is_platform_only, module.name
        assert module.access.platform_reason
        assert module.access.assignable is False, module.name


def test_a_module_may_only_claim_the_registered_permission_by_value() -> None:
    """`ModuleSpec.permissions` stands to the model as `emits` stands to the event catalog.

    Matched by value, which is what the event, job and operation catalogs all do and all
    say why: a same-name claim carrying a different floor or a different label would let a
    module present its version of a row while the control plane documents another. This is
    also where a *label* shadow is caught — `shadowed_requirements` compares only rank
    floors, because an `AuthorizationRequirement` does not carry the label.
    """
    declared = Permission("notes.delete", min_role=EDITOR, label="Delete a note")
    plane = ControlPlane(permissions=PermissionModel(permissions=[declared]))

    def claiming(permission: Permission) -> ModuleSpec:
        return ModuleSpec(
            name="notes", policy=Policy.default(), permissions=(permission,)
        )

    assert plane.validation_errors([claiming(declared)]) == ()

    for wrong, why in (
        (Permission("notes.delete", min_role=VIEWER, label="Delete a note"), "floor"),
        (Permission("notes.delete", min_role=EDITOR, label="Remove a note"), "label"),
        (Permission("notes.archive", min_role=EDITOR, label="Archive a note"), "name"),
    ):
        (error,) = plane.validation_errors([claiming(wrong)])
        assert "claims permission" in error, why
        assert wrong.name in error, why


def test_control_plane_refuses_a_policy_citing_a_same_name_authority_at_another_rank() -> None:
    """A registered *name* is not the registered *entry* — and the gap is a privilege one.

    `Policy` keeps the rank floor of whichever object it was handed, while every view (the
    access graph, `terp grant`'s catalog, the Studio matrix) reports the floor the control
    plane declares. So before this check, `Policy(read=Role("admin", rank=1))` booted clean,
    admitted every viewer, and was displayed as admin-only. The permission form is the same
    defect with a `min_role` instead of a rank.

    This is the check `OperationCatalog.has_operation` already makes by matching an
    operation by value rather than by id, for the reason its docstring gives: accepting a
    same-id definition "would let a route present one wording while the catalog documents
    another". An authority shadow is that with a rank attached.
    """
    plane = ControlPlane(permissions=PermissionModel.default())

    # The role form. rank=1 is far below the declared admin (30), so viewer (10) and editor
    # (20) both sit in the gap and clear a floor the declaration would have refused them.
    weak_admin = Role("admin", rank=1)
    spec = ModuleSpec(name="billing", policy=Policy(read=weak_admin, write=weak_admin))
    (error,) = plane.validation_errors([spec])
    assert "cites 'role:admin' with rank floor 1" in error
    assert "declares it at 30" in error

    # The permission form, against a model that declares it at ADMIN.
    declared = Permission("invoices.approve", min_role=ADMIN)
    shadow = Permission("invoices.approve", min_role=VIEWER)
    declaring = ControlPlane(permissions=PermissionModel(permissions=[declared]))
    shadowing = ModuleSpec(name="invoices", policy=Policy(write=shadow))
    (permission_error,) = declaring.validation_errors([shadowing])
    assert "cites 'permission:invoices.approve' with rank floor 10" in permission_error

    # Referencing the declared object is what the message asks for, and it passes. Without
    # this half, the assertions above hold just as well against a check that refuses every
    # permission requirement outright.
    honest = ModuleSpec(name="invoices", policy=Policy(write=declared))
    assert declaring.validation_errors([honest]) == ()


def test_a_shadow_is_only_a_shadow_when_a_declared_role_sits_in_the_gap() -> None:
    """The window is the whole rule, and it is what keeps ADR 0022 true.

    Every bundled capability pins ``Policy(read_role=Roles.ADMIN)`` at rank 30. ADR 0022
    says the role model is the app's, so an app may declare its own ``admin`` at 40 — and
    then the cited floor (30) and the declared floor (40) are the *same gate by different
    numbers* as long as no role occupies 30..39. Refusing that is a false positive, and a
    check that refused it would make the framework's own capabilities unmountable by any app
    that re-ranked the tier.

    Put a role inside the gap and the two floors stop agreeing: `manager` clears 30 but not
    40, so the capability router admits someone the declaration excludes. That is the defect,
    and the gap is how it is told apart from the harmless case.
    """
    capability_like = ModuleSpec(
        name="users", policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN)
    )

    sparse = ControlPlane(
        permissions=PermissionModel(roles=(VIEWER, EDITOR, Role("admin", rank=40)))
    )
    assert sparse.validation_errors([capability_like]) == ()

    dense = ControlPlane(
        permissions=PermissionModel(
            roles=(VIEWER, EDITOR, Role("manager", rank=35), Role("admin", rank=40))
        )
    )
    (error,) = dense.validation_errors([capability_like])
    assert "cites 'role:admin' with rank floor 30" in error
    assert "declares it at 40" in error


def test_a_shadowed_authority_is_reported_once_not_per_requirement() -> None:
    # A policy naming the same authority for reads and writes is the common case, so the
    # semicolon-joined BootError would otherwise carry the same long sentence twice.
    plane = ControlPlane(permissions=PermissionModel.default())
    weak = Role("editor", rank=2)
    spec = ModuleSpec(name="billing", policy=Policy(read=weak, write=weak))
    assert len(plane.validation_errors([spec])) == 1


def test_policy_public_requires_justification() -> None:
    policy = Policy.public(reason="liveness probe")
    assert policy.authenticated is False
    assert policy.is_public is True
    assert policy.allows_public_writes is False
    public_write = Policy.public_write(reason="login endpoint")
    assert public_write.is_public is True
    assert public_write.allows_public_writes is True
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            Policy.public(reason=bad)
        with pytest.raises(ValueError):
            Policy.public_write(reason=bad)
    with pytest.raises(ValueError, match="authenticated=False"):
        Policy(public_reason="bypassed helper")
    with pytest.raises(ValueError, match="non-empty"):
        Policy(authenticated=False, public_reason=" ")
    with pytest.raises(ValueError, match="public_write_reason requires a non-empty"):
        Policy(authenticated=False, public_reason="ok", public_write_reason=" ")
    with pytest.raises(ValueError, match="public_write_reason requires public_reason"):
        Policy(public_write_reason="bypassed helper")
    # Every Policy construction error carries its own remedy (agent ergonomics):
    # the message names the `terp guide` recipe teaching the compliant pattern.
    with pytest.raises(ValueError, match=r"fix recipe: terp guide policy"):
        Policy(read=Roles.VIEWER, read_role=Roles.VIEWER)
    with pytest.raises(ValueError, match=r"fix recipe: terp guide policy"):
        Policy(write=Roles.EDITOR, write_role=Roles.EDITOR)


def test_module_spec_denies_by_default_and_validates_name() -> None:
    spec = ModuleSpec(name="billing")
    # Policy is intentionally None so the composition root fails closed.
    assert spec.policy is None
    assert spec.tenant_scoped is False
    for bad in ("123", "a-b", "a b", ""):
        with pytest.raises(ValueError):
            ModuleSpec(name=bad)


def test_module_spec_validates_max_request_bytes() -> None:
    """The declared per-module request allowance (ADR 0067) is positive-or-absent."""
    assert ModuleSpec(name="billing").max_request_bytes is None
    assert ModuleSpec(name="billing", max_request_bytes=1).max_request_bytes == 1
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_request_bytes must be positive"):
            ModuleSpec(name="billing", max_request_bytes=bad)


def test_base_update_schema_requires_version() -> None:
    assert BaseUpdateSchema.model_fields["version"].is_required()


def test_base_update_schema_rejects_unknown_fields() -> None:
    # exclude_unset patching silently no-ops a mistyped field name unless the
    # schema forbids extras — a validation error here is the client's only signal.
    class _Update(BaseUpdateSchema):
        body: str | None = Field(default=None, max_length=20)

    with pytest.raises(ValidationError, match="content"):
        _Update.model_validate({"version": 1, "content": "oops"})
    assert _Update.model_validate({"version": 1, "body": "ok"}).body == "ok"


def test_base_table_wires_optimistic_concurrency() -> None:
    class _OccProbe(BaseTable, table=True):
        __tablename__ = "_occ_probe"
        label: str = Field(max_length=20)

    assert "version" in _OccProbe.model_fields
    assert _OccProbe.__mapper__.version_id_col is _OccProbe.__table__.c.version


def test_error_codes_are_unique() -> None:
    seen: dict[str, list[str]] = {}
    stack: list[type[AppError]] = [AppError]
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        seen.setdefault(cls.code, []).append(cls.__name__)
    duplicates = {code: names for code, names in seen.items() if len(names) > 1}
    assert not duplicates, f"duplicate error codes: {duplicates}"


def test_error_envelope_shape() -> None:
    envelope = build_error_envelope(NotFoundError("missing"), request_id="req-1")
    assert envelope == {"code": "not_found", "detail": "missing", "request_id": "req-1"}
