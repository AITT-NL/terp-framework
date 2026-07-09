"""``terp inspect access`` — the Access Graph (module / endpoint / data layers).

Proves the three-layer contract the Studio visualizes: module policy, per-endpoint
effective requirement, and the data layer's row-visibility / write-authority traits,
combined into one stable JSON document (plus a human text rendering). The example
app is the fixture: journals (OwnedMixin), projects (TenantScopedMixin), notes
(plain BaseService), tasks (SoftDeleteMixin).
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import inspect_access, main
from terp.cli.access import build_access_graph, render_access

_MODULES = (
    "app.modules.journals.module:module",
    "app.modules.notes.module:module",
    "app.modules.projects.module:module",
    "app.modules.tasks.module:module",
)


def _with_example_on_path(call):
    example_root = _REPO_ROOT / "apps" / "example"
    sys.path.insert(0, str(example_root))
    try:
        return call()
    finally:
        sys.path.remove(str(example_root))


def _graph() -> dict:
    return json.loads(
        _with_example_on_path(
            lambda: inspect_access(
                "control_plane:control_plane", modules=_MODULES, fmt="json"
            )
        )
    )


def _module(graph: dict, name: str) -> dict:
    return next(m for m in graph["modules"] if m["name"] == name)


def test_access_graph_json_contract_top_level() -> None:
    graph = _graph()
    assert set(graph) == {
        "roles",
        "permissions",
        "modules",
        "scope_predicates",
        "object_authz_predicates",
    }
    assert [role["name"] for role in graph["roles"]] == ["viewer", "editor", "admin"]
    assert [role["rank"] for role in graph["roles"]] == [10, 20, 30]
    assert [m["name"] for m in graph["modules"]] == sorted(m["name"] for m in graph["modules"])


def test_access_graph_endpoint_layer_maps_verbs_to_requirements() -> None:
    graph = _graph()
    notes = _module(graph, "notes")
    assert notes["prefix"] == "/api/v1/notes"
    assert notes["policy"] == {
        "public": False,
        "authenticated": True,
        "read": "role:viewer",
        "write": "role:editor",
    }
    by_key = {
        (endpoint["path"], method): endpoint
        for endpoint in notes["endpoints"]
        for method in endpoint["methods"]
    }
    listing = by_key[("/api/v1/notes/", "GET")]
    assert listing["kind"] == "read"
    assert listing["requirement"] == "role:viewer"
    creating = by_key[("/api/v1/notes/", "POST")]
    assert creating["kind"] == "write"
    assert creating["requirement"] == "role:editor"
    assert creating["extra_permissions"] == []


def test_access_graph_data_layer_reports_owner_trait_and_warning() -> None:
    journals = _module(_graph(), "journals")
    (model,) = journals["models"]
    assert model["model"] == "Journal"
    assert model["traits"]["owned"] is True
    assert model["traits"]["tenant_scoped"] is False
    assert "owner" in model["write_authority"]
    # The honest gap: OwnedMixin is the write gate only — the graph must say so.
    assert any("writes only" in warning for warning in journals["warnings"])


def test_access_graph_data_layer_reports_tenant_trait() -> None:
    projects = _module(_graph(), "projects")
    (model,) = projects["models"]
    assert model["traits"]["tenant_scoped"] is True
    assert "tenant" in model["read_scope"]
    assert "tenant-context" in model["write_authority"]


def test_access_graph_reports_registered_predicates_by_name() -> None:
    graph = _graph()
    assert any(
        "_journal_visibility_predicate" in name for name in graph["scope_predicates"]
    )
    assert any("tenancy" in name for name in graph["scope_predicates"])


def test_access_graph_warns_when_module_declares_no_services() -> None:
    from fastapi import APIRouter

    from terp.core import ControlPlane, ModuleSpec, PermissionModel, Policy

    router = APIRouter()

    @router.get("/")
    def listing() -> dict:  # pragma: no cover - never called
        return {}

    spec = ModuleSpec(name="widgets", router=router, policy=Policy.default())
    graph = build_access_graph(
        ControlPlane(permissions=PermissionModel()), [spec]
    )
    (module,) = graph["modules"]
    assert any("not visualizable" in warning for warning in module["warnings"])


def test_access_graph_marks_route_level_permission_dependencies() -> None:
    from fastapi import APIRouter, Depends

    from terp.capabilities.access import require_permission
    from terp.core import (
        ControlPlane,
        EDITOR,
        ModuleSpec,
        Permission,
        PermissionModel,
        Policy,
    )

    approve = Permission("widgets.approve", min_role=EDITOR)
    router = APIRouter()

    @router.post("/approve", dependencies=[Depends(require_permission("widgets.approve"))])
    def approve_widget() -> dict:  # pragma: no cover - never called
        return {}

    spec = ModuleSpec(name="widgets", router=router, policy=Policy.default())
    graph = build_access_graph(
        ControlPlane(permissions=PermissionModel(permissions=(approve,))), [spec]
    )
    assert graph["permissions"] == [{"name": "widgets.approve", "min_role": "editor"}]
    (module,) = graph["modules"]
    (endpoint,) = module["endpoints"]
    assert endpoint["extra_permissions"] == ["widgets.approve"]


def test_access_graph_renders_public_policy() -> None:
    from fastapi import APIRouter

    from terp.core import ControlPlane, ModuleSpec, PermissionModel, Policy

    router = APIRouter()

    @router.get("/")
    def probe() -> dict:  # pragma: no cover - never called
        return {}

    spec = ModuleSpec(
        name="health", router=router, policy=Policy.public(reason="health probe")
    )
    graph = build_access_graph(ControlPlane(permissions=PermissionModel()), [spec])
    (module,) = graph["modules"]
    assert module["policy"]["public"] is True
    assert module["policy"]["public_reason"] == "health probe"
    (endpoint,) = module["endpoints"]
    assert endpoint["requirement"] == "public"
    text = render_access(ControlPlane(permissions=PermissionModel()), [spec])
    assert "policy public (health probe)" in text


def test_access_graph_text_rendering_smoke() -> None:
    output = _with_example_on_path(
        lambda: inspect_access("control_plane:control_plane", modules=_MODULES)
    )
    assert "Access graph" in output
    assert "Module journals" in output
    assert "read-scope: tenant" in output
    assert "write-authority: owner" in output
    assert "Row-scope predicates (app-wide)" in output


def test_main_inspect_access_prints_graph(capsys) -> None:
    _with_example_on_path(
        lambda: main(
            [
                "inspect",
                "access",
                "--module",
                "app.modules.notes.module:module",
                "--format",
                "json",
            ]
        )
    )
    graph = json.loads(capsys.readouterr().out)
    assert [m["name"] for m in graph["modules"]] == ["notes"]


def test_inspect_access_rejects_wrong_object_type() -> None:
    with pytest.raises(SystemExit):
        _with_example_on_path(
            lambda: inspect_access("app.modules.notes.module:module")
        )
