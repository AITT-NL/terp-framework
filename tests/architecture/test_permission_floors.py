"""Permission grants cannot bypass their declared role floor at a real route."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from terp.capabilities.access import (
    AccessService,
    ModuleRoleService,
    require_permission,
    resolve_module_rank,
)
from terp.capabilities.groups import GroupCreate, GroupsService, register_group_expansion
from terp.core import (
    ADMIN, EDITOR, VIEWER, AuthenticationError, ControlPlane, ModuleAccess,
    ModuleSpec, Permission, PermissionDeniedError, PermissionModel, Policy,
    Principal, RequestAuthorization, Role, create_app, get_session,
    request_authorization, route_policy,
)
from terp.core.request_authorization import _AUTHORIZATION_SCOPE_KEY

EXPORT = Permission("records.export", EDITOR)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    register_group_expansion()
    try:
        yield engine
    finally:
        engine.dispose()


def _client(engine, actor, *, permission=EXPORT, access=None, public=False):
    router = APIRouter()
    policy = Policy.public(reason="dependency supplies the requirement") if public else Policy.default()

    @router.get("/export", response_model=str, dependencies=[Depends(require_permission(permission))])
    @route_policy(policy)
    def export() -> str:
        return "authorized export"

    spec = ModuleSpec(
        name="records", router=router, permissions=(EXPORT,), access=access,
        policy=policy,
    )
    app = create_app(
        [spec], discover_capabilities=False, principal_provider=lambda: actor[0],
        control_plane=ControlPlane(permissions=PermissionModel(permissions=(EXPORT,))),
        module_rank_resolver=resolve_module_rank,
    )

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    return TestClient(app)


@pytest.mark.parametrize("via_group", [False, True])
@pytest.mark.parametrize("as_name", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_role_floor_survives_grant_and_later_role_demotion(engine, via_group, as_name, public):
    subject = uuid.uuid4()
    actor = [Principal(subject, VIEWER)]
    with Session(engine) as session:
        target = subject
        if via_group:
            groups = GroupsService()
            target = groups.create(session, GroupCreate(name="Export reviewers")).id
            groups.add_member(session, target, subject)
        AccessService().grant(session, target, EXPORT.name)
    with _client(engine, actor, permission=EXPORT.name if as_name else EXPORT, public=public) as client:
        assert client.get("/api/v1/records/export").status_code == 403
        actor[0] = Principal(subject, EDITOR)
        assert client.get("/api/v1/records/export").status_code == 200
        actor[0] = Principal(subject, VIEWER)
        assert client.get("/api/v1/records/export").status_code == 403
        actor[0] = Principal(subject, ADMIN)
        with Session(engine) as session:
            assert AccessService().revoke(session, target, EXPORT.name)
        assert client.get("/api/v1/records/export").status_code == 403


@pytest.mark.parametrize("access", [None, ModuleAccess.platform_only(reason="authority management"), ModuleAccess(label="Records", assignable=True)])
@pytest.mark.parametrize("rank", [EDITOR.rank, 999])
def test_dependency_uses_only_declared_module_elevation(engine, access, rank):
    actor = [Principal(uuid.uuid4(), VIEWER)]
    with Session(engine) as session:
        AccessService().grant(session, actor[0].id, EXPORT.name)
        ModuleRoleService().assign(session, actor[0].id, "records", rank)
    with _client(engine, actor, access=access) as client:
        allowed = access is not None and access.assignable and rank == EDITOR.rank
        assert client.get("/api/v1/records/export").status_code == (200 if allowed else 403)


def test_public_route_dependency_refuses_an_unregistered_global_role(engine):
    actor = [Principal(uuid.uuid4(), Role("invented", 999))]
    with Session(engine) as session:
        AccessService().grant(session, actor[0].id, EXPORT.name)
    with _client(engine, actor, public=True) as client:
        assert client.get("/api/v1/records/export").status_code == 403
        actor[0] = None
        assert client.get("/api/v1/records/export").status_code == 401


def test_direct_dependency_requires_typed_floor_and_rejects_unknown_catalog_entries(engine):
    actor = Principal(uuid.uuid4(), ADMIN)
    connection = Request({"type": "http", _AUTHORIZATION_SCOPE_KEY: RequestAuthorization(PermissionModel(permissions=(EXPORT,)))})
    with Session(engine) as session:
        AccessService().grant(session, actor.id, EXPORT.name)
        AccessService().grant(session, actor.id, "missing.permission")
        require_permission(EXPORT)(session=session, principal=actor)
        require_permission(EXPORT.name)(session=session, principal=actor, connection=connection)
        for permission, context in (
            (EXPORT.name, None),
            ("missing.permission", connection),
            (Permission(EXPORT.name, VIEWER), connection),
        ):
            with pytest.raises(PermissionDeniedError):
                require_permission(permission)(session=session, principal=actor, connection=context)
        with pytest.raises(AuthenticationError):
            require_permission(EXPORT)(session=session, principal=None)
    assert request_authorization(Request({"type": "http"})) is None
    assert request_authorization(Request({"type": "http", _AUTHORIZATION_SCOPE_KEY: "forged"})) is None
