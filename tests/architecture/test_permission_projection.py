"""The permission matrix retains and replays every dependency's role floor."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends

from terp.capabilities.access import require_permission
from terp.core import ADMIN, EDITOR, VIEWER, ControlPlane, ModuleSpec, Permission, PermissionModel, Policy
from terp.core.authz import build_access_model, endpoint_json, module_json
from terp.core.routing import (
    mark_required_permission,
    required_permission,
    required_permission_ref,
    route_permission_names,
    route_permission_refs,
)

EXPORT = Permission("records.export", ADMIN, label="Export records")
READ = Permission("records.read", VIEWER, label="Read records")
LADDER = (VIEWER, EDITOR, ADMIN)
PLANE = ControlPlane(permissions=PermissionModel(permissions=(EXPORT, READ)))


def _spec(*permissions: Permission | str, policy: Policy | None) -> ModuleSpec:
    router = APIRouter()

    @router.get("/export", dependencies=[Depends(require_permission(p)) for p in permissions])
    def export() -> str:
        return "export"

    return ModuleSpec(name="records", router=router, policy=policy)


def _endpoint(spec: ModuleSpec) -> dict:
    return build_access_model(PLANE, [spec])["modules"][0]["endpoints"][0]


def _reasons(endpoint: dict) -> list[str]:
    assert all(not row["allowed"] for row in endpoint["by_role"])
    return [row["reason"] for row in endpoint["by_role"]]


def test_permission_markers_keep_typed_floors_through_nested_signature_dependencies() -> None:
    typed = require_permission(EXPORT)
    legacy = require_permission(READ.name)

    def nested(_: None = Depends(typed)) -> None:
        pass

    router = APIRouter()

    @router.get("/export", dependencies=[Depends(nested)])
    def export(_: None = Depends(legacy)) -> str:
        return "export"

    route = router.routes[0]
    assert required_permission_ref(typed) is EXPORT
    assert required_permission(typed) == EXPORT.name
    assert required_permission_ref(legacy) == READ.name
    assert required_permission(legacy) == READ.name
    assert route_permission_refs(route) == [EXPORT, READ.name]
    assert route_permission_names(route) == [EXPORT.name, READ.name]
    assert route_permission_refs(object()) == []
    assert required_permission_ref(None) is None
    assert required_permission(None) is None

    # An unrelated, malformed attribute is not a permission declaration.
    def invalid() -> None:
        pass

    setattr(invalid, "__terp_required_permission__", object())
    assert required_permission_ref(invalid) is None
    assert mark_required_permission(invalid, EXPORT) is invalid
    assert required_permission_ref(invalid) is EXPORT


@pytest.mark.parametrize("as_name", [False, True])
@pytest.mark.parametrize(
    "policy",
    [Policy.default(), Policy.public(reason="the dependency gates this route")],
)
def test_dependency_floor_is_projected_above_the_module_floor(policy, as_name) -> None:
    endpoint = _endpoint(_spec(EXPORT.name if as_name else EXPORT, policy=policy))
    assert endpoint["extra_permissions"] == [EXPORT.name]
    # A held grant cannot make viewer/editor pass the runtime dependency. Only
    # admin clears this permission's own floor and can proceed with its grant.
    assert _reasons(endpoint) == ["rank", "rank", "grant"]


def test_dependency_rank_denial_outranks_a_missing_module_or_other_dependency_grant() -> None:
    spec = _spec(READ, EXPORT, policy=Policy(read=READ, write=READ))
    assert _reasons(_endpoint(spec)) == ["rank", "rank", "grant"]


@pytest.mark.parametrize("permission", ["missing.permission", Permission("missing.permission", VIEWER)])
def test_unregistered_dependency_is_never_reported_as_grant_eligible(permission) -> None:
    endpoint = _endpoint(_spec(permission, policy=Policy.public(reason="gated by dependency")))
    assert _reasons(endpoint) == ["unknown_permission"] * 3


def test_projection_refuses_shadowed_floors_but_labels_do_not_change_authority() -> None:
    shadow = Permission(EXPORT.name, VIEWER)
    assert _reasons(_endpoint(_spec(shadow, policy=Policy.default()))) == ["unknown_permission"] * 3
    same_authority = Permission(EXPORT.name, ADMIN, label="Another display label")
    assert _reasons(_endpoint(_spec(same_authority, policy=Policy.default()))) == ["rank", "rank", "grant"]


def test_standalone_projection_preserves_typed_requirements_and_denies_unresolved_names() -> None:
    typed = _spec(EXPORT, policy=Policy.default())
    assert _reasons(endpoint_json(typed, typed.router.routes[0], LADDER)) == ["rank", "rank", "grant"]
    assert _reasons(module_json(typed, LADDER)["endpoints"][0]) == ["rank", "rank", "grant"]
    legacy = _spec(EXPORT.name, policy=Policy.default())
    assert _reasons(endpoint_json(legacy, legacy.router.routes[0], LADDER)) == ["unknown_permission"] * 3
    assert _reasons(endpoint_json(legacy, legacy.router.routes[0], LADDER, plane=PLANE)) == ["rank", "rank", "grant"]


def test_missing_module_policy_still_denies_every_role() -> None:
    assert _reasons(_endpoint(_spec(EXPORT, policy=None))) == ["no_policy"] * 3


def test_strict_dependency_floor_also_outweighs_an_unresolved_permission() -> None:
    spec = _spec("missing.permission", EXPORT, policy=Policy.default())
    assert _reasons(_endpoint(spec)) == ["rank", "rank", "unknown_permission"]
