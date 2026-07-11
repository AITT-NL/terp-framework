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
        "kernel_routes",
        "omitted_routes",
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


def test_access_graph_surfaces_missing_policy_and_empty_predicate_edges(
    monkeypatch,
) -> None:
    """Fail-visible edges the example app never exercises: a module with no
    Policy (boot would refuse it), a declared service whose ``model`` is not a
    table, an empty row-scope registry, and a named object-authz predicate. The
    graph and its text rendering must surface each — never silently drop them."""
    from fastapi import APIRouter

    from terp.cli import access as access_mod
    from terp.core import (
        ControlPlane,
        EDITOR,
        ModuleSpec,
        Permission,
        PermissionModel,
    )

    def _demo_object_authz() -> bool:  # reported by name only, never invoked here
        return True  # pragma: no cover - listed in the graph, not called

    # App-wide predicate registries are global; pin them for a deterministic view.
    monkeypatch.setattr(access_mod, "registered_scope_predicates", lambda: ())
    monkeypatch.setattr(
        access_mod,
        "registered_object_authz_predicates",
        lambda: (_demo_object_authz,),
    )

    class _ServiceWithoutModel:
        model = None  # not a table type -> the data layer skips this entry

    router = APIRouter()

    @router.get("/")
    def listing() -> dict:  # pragma: no cover - never called
        return {}

    spec = ModuleSpec(
        name="orphan",
        router=router,
        services=(_ServiceWithoutModel,),
        policy=None,  # no Policy declared -> deny-by-default at mount time
    )
    plane = ControlPlane(
        permissions=PermissionModel(
            permissions=(Permission("orphan.approve", min_role=EDITOR),)
        )
    )

    graph = build_access_graph(plane, [spec])
    (module,) = graph["modules"]
    assert module["policy"] is None
    assert module["models"] == []
    (endpoint,) = module["endpoints"]
    assert endpoint["requirement"] == "denied (no policy declared)"
    assert any("deny-by-default" in warning for warning in module["warnings"])

    text = render_access(plane, [spec], fmt="text")
    assert "orphan.approve  editor+" in text
    assert "policy <missing> (boot refuses this module)" in text
    assert "Row-scope predicates (app-wide)\n  <none registered>" in text
    predicate_name = f"{_demo_object_authz.__module__}.{_demo_object_authz.__qualname__}"
    assert f"  {predicate_name}" in text


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


_EXAMPLE_ROOT = str(_REPO_ROOT / "apps" / "example")


def _app_graph() -> dict:
    from terp.cli.access import build_access_graph_for_app

    def _build():
        from app.main import build

        return build_access_graph_for_app(build())

    return _with_example_on_path(_build)


def test_access_graph_for_app_covers_the_whole_composed_surface() -> None:
    # The leak the hand-passed --module form has: a composed app mounts client
    # modules AND every discovered capability router; --app must report them all.
    graph = _app_graph()
    names = {m["name"] for m in graph["modules"]}
    assert {"access", "audit", "groups", "users", "files", "webhooks"} <= names
    assert {"auth", "me", "notes", "tasks", "projects", "journals"} <= names
    # Fail-closed reconciliation against app.openapi(): nothing mounted is missing.
    assert graph["omitted_routes"] == []
    # Every reachable non-module surface is surfaced, never silently dropped:
    # the kernel health routes AND the schema-hidden FastAPI docs routes.
    kernel_paths = {r["path"] for r in graph["kernel_routes"]}
    assert {"/health/live", "/health/ready"} <= kernel_paths
    assert {"/openapi.json", "/docs", "/redoc"} <= kernel_paths
    # A discovered capability's endpoint carries its real per-endpoint requirement.
    groups = next(m for m in graph["modules"] if m["name"] == "groups")
    listing = next(e for e in groups["endpoints"] if e["path"] == "/api/v1/groups/")
    assert "admin" in listing["requirement"]


def test_inspect_access_app_mode_json_reports_every_capability(capsys) -> None:
    main(
        [
            "inspect",
            "access",
            "--app",
            "app.main:build",
            "--app-root",
            _EXAMPLE_ROOT,
            "--format",
            "json",
        ]
    )
    graph = json.loads(capsys.readouterr().out)
    names = {m["name"] for m in graph["modules"]}
    assert {"groups", "users", "audit", "files", "webhooks", "access"} <= names
    assert graph["omitted_routes"] == []


def test_inspect_access_app_mode_text_lists_kernel_routes(capsys) -> None:
    main(
        [
            "inspect",
            "access",
            "--app",
            "app.main:build",
            "--app-root",
            _EXAMPLE_ROOT,
        ]
    )
    out = capsys.readouterr().out
    assert "Kernel / unauthenticated routes" in out
    assert "/health/live" in out
    assert "Module groups" in out


def test_build_access_graph_for_app_rejects_a_non_terp_app() -> None:
    from fastapi import FastAPI

    from terp.cli.access import build_access_graph_for_app

    with pytest.raises(ValueError, match="not composed by terp.core.create_app"):
        build_access_graph_for_app(FastAPI())


def test_access_graph_flags_a_mounted_route_absent_from_the_graph() -> None:
    # The fail-visible half: a route the composed app serves but the recorded specs
    # do not cover must appear under omitted_routes, never vanish.
    from fastapi import APIRouter, FastAPI

    from terp.cli.access import build_access_graph_for_app, render_access_graph
    from terp.core import ControlPlane, PermissionModel

    app = FastAPI()
    router = APIRouter()

    @router.get("/")
    def ghost() -> dict:  # pragma: no cover - never called
        return {}

    app.include_router(router, prefix="/api/v1/ghost")
    app.state.terp_module_specs = ()
    app.state.terp_control_plane = ControlPlane(permissions=PermissionModel())

    graph = build_access_graph_for_app(app)
    assert graph["omitted_routes"] == [{"path": "/api/v1/ghost/", "methods": ["GET"]}]
    text = render_access_graph(graph, fmt="text")
    assert "OMITTED served routes" in text
    assert "/api/v1/ghost/" in text


def test_access_graph_flags_nested_router_routes_instead_of_dropping_them() -> None:
    # A route on a NESTED included router is served (it is in app.openapi()) but the
    # spec-level endpoint extraction is flat — it must surface as an omitted-route
    # alarm, never silently vanish from the permission report.
    from fastapi import APIRouter, FastAPI

    from terp.cli.access import build_access_graph_for_app
    from terp.core import ControlPlane, ModuleSpec, PermissionModel, Policy

    nested = APIRouter()

    @nested.get("/nested")
    def deep() -> dict:  # pragma: no cover - never called
        return {}

    parent = APIRouter()

    @parent.get("/")
    def top() -> dict:  # pragma: no cover - never called
        return {}

    parent.include_router(nested, prefix="/deep")
    app = FastAPI()
    app.include_router(parent, prefix="/api/v1/widgets")
    app.state.terp_module_specs = (
        ModuleSpec(name="widgets", router=parent, policy=Policy.default()),
    )
    app.state.terp_control_plane = ControlPlane(permissions=PermissionModel())

    graph = build_access_graph_for_app(app)
    (module,) = graph["modules"]
    assert [e["path"] for e in module["endpoints"]] == ["/api/v1/widgets/"]
    assert graph["omitted_routes"] == [
        {"path": "/api/v1/widgets/deep/nested", "methods": ["GET"]}
    ]


def test_access_graph_reports_mounted_sub_applications() -> None:
    # app.mount() bypasses the ModuleSpec policy guard entirely — the graph must
    # show the mount as reachable-but-unguarded surface, never omit it.
    from fastapi import FastAPI

    from terp.cli.access import build_access_graph_for_app
    from terp.core import ControlPlane, PermissionModel

    app = FastAPI()
    app.mount("/static", FastAPI())

    @app.get("/ping")
    def ping() -> dict:  # pragma: no cover - never called
        return {}

    app.state.terp_module_specs = ()
    app.state.terp_control_plane = ControlPlane(permissions=PermissionModel())

    graph = build_access_graph_for_app(app)
    mounts = [r for r in graph["kernel_routes"] if r["path"] == "/static/*"]
    assert len(mounts) == 1
    assert "not policy-guarded" in mounts[0]["note"]
    # The schema-hidden docs routes are reported alongside it, and a direct
    # (top-level APIRoute) endpoint surfaces through the OpenAPI reconciliation.
    kernel_paths = {r["path"] for r in graph["kernel_routes"]}
    assert kernel_paths >= {"/openapi.json", "/docs", "/ping"}


def test_inspect_access_app_mode_inserts_a_fresh_app_root(tmp_path) -> None:
    # A fresh app_root (not yet on sys.path) exercises the path insertion; the bad
    # app reference then fails closed after the insert (mirrors terp openapi).
    with pytest.raises(SystemExit):
        inspect_access(app=":app", app_root=str(tmp_path))
