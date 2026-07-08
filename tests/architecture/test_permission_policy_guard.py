"""Permission-in-``Policy`` is enforced as a real per-subject grant (ADR 0016).

H1 from the adversarial review: ``Policy(write=Permission(...))`` used to collapse
to the permission's role *rank* in ``build_guard`` — the name was never checked, so
"any editor may write." Now a permission requirement clears the rank floor **and**
must be held (via the injected ``permission_enforcer`` seam, fail-closed without
one), and ``create_app`` refuses to boot when a permission policy has no enforcer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import (
    EDITOR,
    VIEWER,
    ControlPlane,
    ModuleSpec,
    Permission,
    PermissionDeniedError,
    PermissionModel,
    Policy,
    Principal,
    Role,
    create_app,
    get_session,
)
from terp.core.app import build_guard

from terp.capabilities.access import AccessService, enforce_permission
import terp.capabilities.access.models  # noqa: F401  (register the Grant table)

_PUBLISH = Permission("widgets.publish", min_role=EDITOR)
_POLICY = Policy(read=VIEWER, write=_PUBLISH)
_POST = SimpleNamespace(method="POST")
_GET = SimpleNamespace(method="GET")


def _editor() -> Principal:
    return Principal(id=uuid.uuid4(), role=EDITOR)


def _viewer() -> Principal:
    return Principal(id=uuid.uuid4(), role=VIEWER)


# --------------------------------------------------------------------------- #
# build_guard — the permission branch (direct calls, no FastAPI)
# --------------------------------------------------------------------------- #
def test_permission_write_allowed_when_granted() -> None:
    guard = build_guard(_POLICY, permission_enforcer=lambda _s, _i, _n: True)
    guard(_POST, principal=_editor(), session=None)  # no raise


def test_permission_write_denied_without_grant() -> None:
    guard = build_guard(_POLICY, permission_enforcer=lambda _s, _i, _n: False)
    with pytest.raises(PermissionDeniedError):
        guard(_POST, principal=_editor(), session=None)


def test_permission_write_denied_below_rank_floor() -> None:
    # A viewer is below the EDITOR floor — denied before the grant is consulted.
    guard = build_guard(_POLICY, permission_enforcer=lambda _s, _i, _n: True)
    with pytest.raises(PermissionDeniedError):
        guard(_POST, principal=_viewer(), session=None)


def test_permission_write_denied_when_no_enforcer_installed() -> None:
    # Defensive runtime fail-closed (create_app also refuses this at boot).
    guard = build_guard(_POLICY, permission_enforcer=None)
    with pytest.raises(PermissionDeniedError):
        guard(_POST, principal=_editor(), session=None)


def test_role_read_requirement_skips_permission_check() -> None:
    # GET uses read=VIEWER (a role), so no enforcer is consulted even with none set.
    guard = build_guard(_POLICY, permission_enforcer=None)
    guard(_GET, principal=_editor(), session=None)  # no raise


def test_unregistered_principal_role_is_denied_fail_closed() -> None:
    root = Principal(id=uuid.uuid4(), role=Role("root", rank=999))
    guard = build_guard(Policy.default(), permission_model=PermissionModel.default())
    with pytest.raises(PermissionDeniedError):
        guard(_GET, principal=root, session=None)


# --------------------------------------------------------------------------- #
# End-to-end over HTTP: 403 without the grant, 200 once granted
# --------------------------------------------------------------------------- #
def test_permission_policy_enforced_over_http() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    principal = Principal(id=uuid.uuid4(), role=EDITOR)
    publish = Permission("widgets.publish", min_role=EDITOR)
    plane = ControlPlane(permissions=PermissionModel(permissions=[publish]))

    router = APIRouter()

    @router.post("/")
    def publish_widget() -> dict[str, bool]:
        return {"published": True}

    spec = ModuleSpec(
        name="widgets", router=router, policy=Policy(read=VIEWER, write=publish)
    )
    app = create_app(
        [spec],
        principal_provider=lambda: principal,
        control_plane=plane,
        permission_enforcer=enforce_permission,
    )

    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    try:
        # The editor clears the rank floor but has not been granted the permission.
        assert client.post("/api/v1/widgets/").status_code == 403
        with Session(engine) as session:
            AccessService().grant(session, principal.id, "widgets.publish")
        # Granted now — allowed.
        assert client.post("/api/v1/widgets/").status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
