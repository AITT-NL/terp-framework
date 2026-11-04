"""Stored responses require live credential, route and resource authorization."""
from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlmodel import Session

from terp.capabilities.access import AccessService, require_permission
from terp.capabilities.auth import create_access_token
from terp.capabilities.identity import IdentityService, RefreshTokenService, User
from terp.capabilities.users import UserAdminUpdate, UsersService
from terp.core import (
    EDITOR, ControlPlane, ModuleSpec, Permission, PermissionDeniedError, PermissionModel,
    Policy, Roles, create_app, get_principal, get_session,
    idempotent_replay,
)
from terp.core._internal.session_guard import WriteGuardedSession

WRITE = Permission("records.write", EDITOR)
DETAIL = Permission("records.detail", EDITOR)
_PASSWORD = "correct horse battery"


def _client(engine, user_id, *, dependency_permission=False, write_dependency=False, declared=True):
    effects, cleanup = [], []
    router, service = APIRouter(), AccessService()
    resource_id = uuid.uuid4()
    resource_permission = f"records.resource.{resource_id}"
    with Session(engine) as session:
        for permission in (WRITE.name, DETAIL.name, resource_permission):
            service.grant(session, user_id, permission)
        principal = IdentityService().principal_for_id(session, user_id)
        token = create_access_token(subject=principal.id, role=principal.role, token_version=principal.token_version)

    def resource_authorizer(
        record_id: uuid.UUID, session=Depends(get_session), principal=Depends(get_principal),
    ):
        try:
            if not service.has_permission(session, principal.id, f"records.resource.{record_id}"):
                raise PermissionDeniedError()
            if write_dependency:
                # A mistaken write in an authorization dependency must never repeat.
                service.grant(session, user_id, f"records.effect.{len(effects)}")
            yield
        finally:
            cleanup.append(True)

    dependencies = [Depends(require_permission(DETAIL))] if dependency_permission else []

    def mutate(record_id: uuid.UUID, session=Depends(get_session)) -> dict:
        effects.append(record_id)
        service.grant(session, user_id, "records.persisted")
        return {"resource": str(record_id), "execution": len(effects)}

    if declared:
        mutate = idempotent_replay(authorize=resource_authorizer)(mutate)
    router.post("/{record_id}", response_model=dict, dependencies=dependencies)(mutate)
    spec = ModuleSpec(name="records", router=router, policy=Policy(write=WRITE),
                      permissions=(WRITE, DETAIL))
    app = create_app(
        [spec], discover_capabilities=False,
        principal_provider=IdentityService().principal_provider(),
        permission_enforcer=service.has_permission,
        control_plane=ControlPlane(permissions=PermissionModel(permissions=(WRITE, DETAIL))),
    )

    def sessions():
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "once"}
    return client, f"/api/v1/records/{resource_id}", headers, effects, cleanup, resource_permission


@pytest.mark.parametrize("change", ["revocation", "demotion", "route_grant", "dependency_grant", "resource"])
def test_replay_checks_current_authority_and_keeps_effect_once(db_engine, make_user, change):
    user_id = make_user("retry-authority@example.test", _PASSWORD, Roles.EDITOR)
    client, path, headers, effects, cleanup, resource_permission = _client(
        db_engine, user_id, dependency_permission=True)
    first = client.post(path, headers=headers)
    assert first.status_code == 200, first.text
    retry = client.post(path, headers=headers)
    assert retry.json() == first.json()
    assert retry.headers["idempotency-replayed"] == "true"
    assert len(effects) == 1
    with Session(db_engine) as session:
        users = UsersService(RefreshTokenService().revoke_all_for_user)
        if change == "revocation":
            users.revoke_sessions(session, user_id)
        elif change == "demotion":
            row = session.get(User, user_id)
            users.update(session, user_id, UserAdminUpdate(version=row.version, role=int(Roles.VIEWER)))
        else:
            permission = {"route_grant": WRITE.name, "dependency_grant": DETAIL.name,
                          "resource": resource_permission}[change]
            AccessService().revoke(session, user_id, permission)
    for _ in range(2):
        denied = client.post(path, headers=headers)
        assert denied.status_code == (401 if change in {"revocation", "demotion"} else 403)
        assert "idempotency-replayed" not in denied.headers
        assert len(effects) == 1
    # Restoring a grant proves denial retained the completed key rather than releasing
    # it and allowing the mutation to execute again on the next authorized request.
    if change not in {"revocation", "demotion"}:
        with Session(db_engine) as session:
            AccessService().grant(session, user_id, permission)
        restored = client.post(path, headers=headers)
        assert restored.json() == first.json()
        assert restored.headers["idempotency-replayed"] == "true"
        assert len(effects) == 1
    assert cleanup  # Yield dependencies close on completed requests and denials.


def test_default_refuses_replay_of_in_handler_authorization(db_engine, make_user):
    user_id = make_user("retry-default@example.test", _PASSWORD)
    client, path, headers, effects, _, _ = _client(db_engine, user_id, declared=False)
    assert client.post(path, headers=headers).status_code == 200
    for _ in range(2):
        denied = client.post(path, headers=headers)
        assert denied.status_code == 409
        assert denied.json()["code"] == "idempotency_replay_not_authorized"
    assert len(effects) == 1


def test_replay_dependency_cannot_write_even_under_post_method(db_engine, make_user):
    user_id = make_user("retry-readonly@example.test", _PASSWORD)
    client, path, headers, effects, cleanup, _ = _client(db_engine, user_id, write_dependency=True)
    assert client.post(path, headers=headers).status_code == 200
    for _ in range(2):
        assert client.post(path, headers=headers).status_code == 500
    assert len(effects) == 1
    assert len(cleanup) == 3
    with Session(db_engine) as session:
        assert AccessService().has_permission(session, user_id, "records.effect.0")
        assert not AccessService().has_permission(session, user_id, "records.effect.1")
    # A separate ordinary request proves the read-only context is reset on failure.
    assert client.post(path, headers={"Authorization": headers["Authorization"]}).status_code == 200
    assert len(effects) == 2
