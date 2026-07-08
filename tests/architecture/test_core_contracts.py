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
    AppError,
    BaseTable,
    BaseUpdateSchema,
    ControlPlane,
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
