"""Phase A CLI smoke tests."""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import inspect_control_plane, main


def _with_example_on_path(call):
    example_root = _REPO_ROOT / "apps" / "example"
    sys.path.insert(0, str(example_root))
    try:
        return call()
    finally:
        sys.path.remove(str(example_root))



def test_inspect_control_plane_renders_authority_map() -> None:
    example_root = _REPO_ROOT / "apps" / "example"
    sys.path.insert(0, str(example_root))
    try:
        output = inspect_control_plane(
            "control_plane:control_plane",
            modules=("app.modules.notes.module:module",),
        )
    finally:
        sys.path.remove(str(example_root))

    assert "Roles" in output
    assert "viewer (10)" in output
    assert "editor (20)" in output
    assert "admin (30)" in output
    assert "Permissions" in output
    assert "Modules" in output
    assert "notes  read=role:viewer  write=role:editor" in output


def test_main_inspect_control_plane_prints_authority_map(capsys) -> None:
    example_root = _REPO_ROOT / "apps" / "example"
    sys.path.insert(0, str(example_root))
    try:
        main([
            "inspect",
            "control-plane",
            "--module",
            "app.modules.notes.module:module",
        ])
    finally:
        sys.path.remove(str(example_root))

    out = capsys.readouterr().out
    assert "viewer (10)" in out
    assert "notes  read=role:viewer  write=role:editor" in out


def test_inspect_control_plane_renders_mermaid() -> None:
    output = _with_example_on_path(
        lambda: inspect_control_plane(
            "control_plane:control_plane",
            modules=("app.modules.notes.module:module",),
            fmt="mermaid",
        )
    )
    assert output.startswith("flowchart LR")
    assert 'role_viewer["viewer"] --> role_editor["editor"]' in output
    assert 'module_notes(["notes"])' in output
    assert "read:viewer" in output


def test_inspect_rejects_wrong_object_types() -> None:
    # A dotted target that is not a ControlPlane / ModuleSpec fails closed.
    with pytest.raises(SystemExit, match="ControlPlane"):
        inspect_control_plane("terp.core:Roles")
    with pytest.raises(SystemExit, match="ModuleSpec"):
        _with_example_on_path(
            lambda: inspect_control_plane(
                "control_plane:control_plane",
                modules=("terp.core:Roles",),
            )
        )


def test_inspect_text_handles_public_and_missing_policy() -> None:
    # Drive the public / missing-policy branches of the text renderer directly.
    from terp.core import ModuleSpec, Policy
    from terp.cli import _render_text  # type: ignore[attr-defined]
    from terp.core import ControlPlane

    specs = [
        ModuleSpec(name="open", policy=Policy.public(reason="health probe")),
        ModuleSpec(name="bare"),
    ]
    rendered = _render_text(ControlPlane.default(), specs)
    assert "open  public (health probe)" in rendered
    assert "bare  policy=<missing>" in rendered


def test_render_text_empty_plane_shows_placeholders() -> None:
    from terp.cli import _render_text  # type: ignore[attr-defined]
    from terp.core import ControlPlane

    rendered = _render_text(ControlPlane.default(), [])
    assert "<none declared>" in rendered  # no permissions declared
    assert "<none provided>" in rendered  # no modules passed


def test_render_text_lists_declared_permissions() -> None:
    from terp.cli import _render_text  # type: ignore[attr-defined]
    from terp.core import ControlPlane, Permission, PermissionModel, VIEWER

    plane = ControlPlane(
        permissions=PermissionModel(permissions=[Permission("billing.read", min_role=VIEWER)])
    )
    rendered = _render_text(plane, [])
    assert "billing.read  viewer+" in rendered


def test_render_mermaid_single_role_and_public_module() -> None:
    from terp.cli import _render_mermaid  # type: ignore[attr-defined]
    from terp.core import ControlPlane, ModuleSpec, PermissionModel, Policy, Role

    plane = ControlPlane(permissions=PermissionModel(roles=[Role("solo", rank=10)]))
    specs = [ModuleSpec(name="pub", policy=Policy.public(reason="probe"))]
    rendered = _render_mermaid(plane, specs)
    assert 'role_solo["solo"]' in rendered  # single-role ladder branch
    assert 'module_pub(["pub"])' in rendered  # public module: no authz edges
    assert "read:" not in rendered


def test_render_mermaid_sanitizes_dotted_permission_names() -> None:
    # Permission names with dots/colons must stay valid Mermaid (ids sanitized,
    # labels quoted) rather than emitting a broken `authz_billing.read` node.
    from terp.cli import _render_mermaid  # type: ignore[attr-defined]
    from terp.core import (
        ControlPlane,
        ModuleSpec,
        Permission,
        PermissionModel,
        Policy,
        VIEWER,
    )

    perm = Permission("billing.read", min_role=VIEWER)
    plane = ControlPlane(permissions=PermissionModel(permissions=[perm]))
    spec = ModuleSpec(name="billing", policy=Policy(read=perm, write=perm))
    rendered = _render_mermaid(plane, [spec])
    assert 'authz_permission_billing_read["permission:billing.read"]' in rendered
    assert "authz_billing.read" not in rendered  # no raw dotted node id
    assert "read:billing.read" in rendered



def test_inspect_control_plane_renders_json() -> None:
    import json

    output = _with_example_on_path(
        lambda: inspect_control_plane(
            "control_plane:control_plane",
            modules=("app.modules.notes.module:module",),
            fmt="json",
        )
    )
    payload = json.loads(output)
    assert {"name": "viewer", "rank": 10} in payload["roles"]
    notes = next(m for m in payload["modules"] if m["name"] == "notes")
    assert notes["policy"] == {
        "public": False,
        "read": "role:viewer",
        "write": "role:editor",
    }
    assert isinstance(payload["permissions"], list)
    assert isinstance(payload["events"], list)
    assert isinstance(payload["jobs"], list)
    assert payload["audit"]["enabled"] is True
    assert payload["passwords"]["min_length"] >= 8
    assert payload["security"]["cors"]["mode"] in {"deny-all", "allow", "disabled"}
    assert isinstance(payload["schedules"], list)
    assert isinstance(payload["job_system_actor"], bool)


def test_render_json_covers_public_missing_policy_and_catalogs() -> None:
    import json

    from terp.cli import _render_json  # type: ignore[attr-defined]
    from terp.core import (
        VIEWER,
        ControlPlane,
        EventCatalog,
        EventDefinition,
        JobCatalog,
        JobDefinition,
        ModuleSpec,
        Permission,
        PermissionModel,
        Policy,
    )
    from terp.core import BaseSchema

    class _Payload(BaseSchema):
        pass

    plane = ControlPlane(
        permissions=PermissionModel(permissions=[Permission("billing.read", min_role=VIEWER)]),
        events=EventCatalog(events=(EventDefinition(name="billing.created", payload_schema=_Payload),)),
        jobs=JobCatalog(
            jobs=(
                JobDefinition(
                    name="billing.sync",
                    payload_schema=_Payload,
                    handler=lambda ctx, payload: None,
                ),
            )
        ),
    )
    specs = [
        ModuleSpec(
            name="open",
            policy=Policy.public(reason="health probe"),
            emits=[EventDefinition(name="billing.created", payload_schema=_Payload)],
            jobs=[
                JobDefinition(
                    name="billing.sync",
                    payload_schema=_Payload,
                    handler=lambda ctx, payload: None,
                )
            ],
        ),
        ModuleSpec(name="bare"),
    ]
    payload = json.loads(_render_json(plane, specs))
    assert payload["permissions"] == [{"name": "billing.read", "min_role": "viewer"}]
    modules = {m["name"]: m for m in payload["modules"]}
    assert modules["open"]["policy"] == {"public": True, "public_reason": "health probe"}
    assert modules["open"]["emits"] == ["billing.created"]
    assert modules["open"]["subscribes"] == []
    assert modules["open"]["jobs"] == ["billing.sync"]
    assert modules["bare"]["policy"] is None
    assert modules["bare"]["emits"] == []
    assert modules["bare"]["subscribes"] == []
    assert modules["bare"]["jobs"] == []
    assert payload["events"][0]["name"] == "billing.created"
    assert payload["events"][0]["payload_schema"] == "_Payload"
    assert payload["jobs"][0]["name"] == "billing.sync"
    assert payload["jobs"][0]["max_attempts"] >= 1
    # Default platform policies: audit on, safe passwords, deny-all CORS, no schedules.
    assert payload["audit"] == {
        "enabled": True,
        "disabled_reason": None,
        "retention_days": None,
        "redact_keys": payload["audit"]["redact_keys"],
    }
    assert "password" in payload["audit"]["redact_keys"]
    assert payload["passwords"]["min_length"] == 12
    assert payload["passwords"]["min_character_classes"] == 2
    assert payload["passwords"]["denylist_size"] > 0
    assert payload["passwords"]["relaxed_reason"] is None
    assert payload["security"]["cors"] == {"mode": "deny-all", "configured": False}
    assert payload["security"]["rate_limit"] == {
        "enabled": True,
        "requests": 240,
        "window_seconds": 60,
    }
    assert payload["security"]["max_request_bytes"] == 1024 * 1024
    assert payload["security"]["trusted_proxy_hops"] == 0
    assert payload["security"]["request_id_header"] == "X-Request-ID"
    assert payload["schedules"] == []
    assert payload["job_system_actor"] is False


def test_render_json_covers_non_default_platform_policies() -> None:
    import json
    import uuid

    from terp.cli import _render_json  # type: ignore[attr-defined]
    from terp.core import (
        AuditPolicy,
        BaseSchema,
        ControlPlane,
        CorsPolicy,
        JobCatalog,
        JobDefinition,
        PasswordPolicy,
        RateLimit,
        ScheduleCatalog,
        ScheduleDefinition,
        SecurityConfig,
    )

    class _Payload(BaseSchema):
        pass

    job = JobDefinition(
        name="billing.sync",
        payload_schema=_Payload,
        handler=lambda ctx, payload: None,
    )
    plane = ControlPlane(
        audit=AuditPolicy.disabled(reason="prototype spike"),
        passwords=PasswordPolicy.relaxed(reason="kiosk PINs"),
        security=SecurityConfig(
            cors=CorsPolicy.allow(["https://app.example"], allow_credentials=True),
            rate_limit=RateLimit.disabled(),
        ),
        jobs=JobCatalog(jobs=(job,)),
        schedules=ScheduleCatalog(
            schedules=(ScheduleDefinition(name="billing.nightly", job=job, cron="0 2 * * *"),)
        ),
        job_system_actor_id=uuid.uuid4(),
    )
    payload = json.loads(_render_json(plane, []))
    assert payload["audit"]["enabled"] is False
    assert payload["audit"]["disabled_reason"] == "prototype spike"
    assert payload["passwords"]["relaxed_reason"] == "kiosk PINs"
    assert payload["security"]["cors"] == {
        "mode": "allow",
        "origins": ["https://app.example"],
        "allow_credentials": True,
    }
    assert payload["security"]["rate_limit"]["enabled"] is False
    assert payload["schedules"] == [
        {"name": "billing.nightly", "cron": "0 2 * * *", "job": "billing.sync"}
    ]
    assert payload["job_system_actor"] is True


def test_render_json_covers_cors_disabled_and_configured_deny_all() -> None:
    import json

    from terp.cli import _render_json  # type: ignore[attr-defined]
    from terp.core import ControlPlane, CorsPolicy, SecurityConfig

    disabled = ControlPlane(
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="same-origin only"))
    )
    payload = json.loads(_render_json(disabled, []))
    assert payload["security"]["cors"] == {
        "mode": "disabled",
        "reason": "same-origin only",
    }

    acknowledged = ControlPlane(security=SecurityConfig(cors=CorsPolicy(configured=True)))
    payload = json.loads(_render_json(acknowledged, []))
    assert payload["security"]["cors"] == {"mode": "deny-all", "configured": True}


def test_render_text_includes_platform_policy_sections() -> None:
    from terp.cli import _render_text  # type: ignore[attr-defined]
    from terp.core import ControlPlane

    rendered = _render_text(ControlPlane.default(), [])
    assert "Audit" in rendered
    assert "enabled  retention=unlimited" in rendered
    assert "Passwords" in rendered
    assert "min_length=12  min_character_classes=2" in rendered
    assert "Security" in rendered
    assert "cors deny-all (unconfigured)" in rendered
    assert "rate_limit 240/60s" in rendered
    assert "max_request_bytes=1048576  trusted_proxy_hops=0" in rendered
    assert "Schedules" in rendered
    assert rendered.count("<none declared>") == 2  # permissions + schedules


def test_render_text_covers_non_default_platform_policies() -> None:
    from terp.cli import _render_text  # type: ignore[attr-defined]
    from terp.core import (
        AuditPolicy,
        BaseSchema,
        ControlPlane,
        CorsPolicy,
        JobCatalog,
        JobDefinition,
        PasswordPolicy,
        RateLimit,
        ScheduleCatalog,
        ScheduleDefinition,
        SecurityConfig,
    )

    class _Payload(BaseSchema):
        pass

    job = JobDefinition(
        name="billing.sync",
        payload_schema=_Payload,
        handler=lambda ctx, payload: None,
    )
    plane = ControlPlane(
        audit=AuditPolicy(retention_days=90),
        passwords=PasswordPolicy.relaxed(reason="kiosk PINs"),
        security=SecurityConfig(
            cors=CorsPolicy.allow(["https://app.example"]),
            rate_limit=RateLimit.disabled(),
        ),
        jobs=JobCatalog(jobs=(job,)),
        schedules=ScheduleCatalog(
            schedules=(ScheduleDefinition(name="billing.nightly", job=job, cron="0 2 * * *"),)
        ),
    )
    rendered = _render_text(plane, [])
    assert "retention=90 days" in rendered
    assert "RELAXED (kiosk PINs)" in rendered
    assert "cors allow https://app.example" in rendered
    assert "rate_limit DISABLED" in rendered
    assert "billing.nightly  0 2 * * *  -> billing.sync" in rendered

    disabled = ControlPlane(
        audit=AuditPolicy.disabled(reason="prototype spike"),
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="same-origin only")),
    )
    rendered = _render_text(disabled, [])
    assert "DISABLED (prototype spike)" in rendered
    assert "cors disabled (same-origin only)" in rendered

    acknowledged = ControlPlane(security=SecurityConfig(cors=CorsPolicy(configured=True)))
    assert "  cors deny-all\n" in _render_text(acknowledged, [])
