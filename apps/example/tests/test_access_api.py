"""End-to-end: the access capability — RBAC permission grants + ``require_permission``.

Three layers are proven: the :class:`AccessService` grant algebra (idempotent
grant / revoke / isolation); the fail-closed ``require_permission`` dependency a
module mounts on a route (401 unauthenticated, 403 without the grant, 200 with);
and the self-registering admin ``access`` router (discovered + ADMIN-only).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.capabilities.access import AccessService, require_permission
from terp.capabilities.auth import create_access_token
from terp.capabilities.auth import get_principal as auth_get_principal
from terp.core import (
    VIEWER,
    ControlPlane,
    ModuleSpec,
    Permission,
    PermissionModel,
    Policy,
    Principal,
    Roles,
    create_app,
    get_session,
)


# --- the service: the grant algebra ----------------------------------------- #
def test_grant_is_idempotent(db_session: Session) -> None:
    access = AccessService()
    subject = uuid.uuid4()
    first = access.grant(db_session, subject, "billing.write")
    again = access.grant(db_session, subject, "billing.write")
    assert first.id == again.id
    assert access.has_permission(db_session, subject, "billing.write")


def test_revoke_removes_a_grant_and_is_safe_when_absent(db_session: Session) -> None:
    access = AccessService()
    subject = uuid.uuid4()
    access.grant(db_session, subject, "reports.export")
    assert access.revoke(db_session, subject, "reports.export") is True
    assert access.has_permission(db_session, subject, "reports.export") is False
    assert access.revoke(db_session, subject, "reports.export") is False


def test_permissions_are_isolated_by_subject(db_session: Session) -> None:
    access = AccessService()
    alice, bob = uuid.uuid4(), uuid.uuid4()
    access.grant(db_session, alice, "p1")
    access.grant(db_session, alice, "p2")
    access.grant(db_session, bob, "p3")
    assert access.permissions_for(db_session, alice) == {"p1", "p2"}
    assert access.permissions_for(db_session, bob) == {"p3"}
    assert access.has_permission(db_session, alice, "p3") is False


# --- require_permission: a module gating one action -------------------------- #
@pytest.fixture
def gated_app() -> Iterator[tuple[FastAPI, Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    gated = APIRouter(tags=["gated"])

    # Declared, and claimed by the module that enforces it. This fixture used to pass the
    # name as a literal against an empty control plane, which is exactly the hole the boot
    # check now closes: a permission nothing declares cannot be granted through `terp grant`
    # or the access API, so the route was closed rather than fine-grained.
    widgets_write = Permission(
        "widgets.write", min_role=VIEWER, label="Change a widget"
    )

    @gated.post(
        "/act",
        response_model=str,
        dependencies=[Depends(require_permission(widgets_write))],
    )
    async def act() -> str:
        return "ok"

    spec = ModuleSpec(
        name="gated",
        router=gated,
        permissions=(widgets_write,),
        policy=Policy.public_write(
            reason="action is gated by a fine-grained grant, not a role"
        ),
    )
    application = create_app(
        [spec],
        principal_provider=auth_get_principal,
        control_plane=ControlPlane(
            permissions=PermissionModel(permissions=(widgets_write,))
        ),
    )

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_session] = _session_override
    try:
        yield application, engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def _bearer(app: FastAPI, subject: uuid.UUID) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {create_access_token(subject=subject, role=Roles.EDITOR)}"
    return client


def test_require_permission_rejects_the_unauthenticated(gated_app: tuple[FastAPI, Engine]) -> None:
    app, _ = gated_app
    assert TestClient(app).post("/api/v1/gated/act").status_code == 401


def test_require_permission_rejects_a_caller_without_the_grant(gated_app: tuple[FastAPI, Engine]) -> None:
    app, _ = gated_app
    assert _bearer(app, uuid.uuid4()).post("/api/v1/gated/act").status_code == 403


def test_require_permission_allows_a_caller_holding_the_grant(gated_app: tuple[FastAPI, Engine]) -> None:
    app, engine = gated_app
    subject = uuid.uuid4()
    with Session(engine) as session:
        AccessService().grant(session, subject, "widgets.write")
    response = _bearer(app, subject).post("/api/v1/gated/act")
    assert response.status_code == 200
    assert response.json() == "ok"


# --- the admin router: discovered + ADMIN-only ------------------------------- #
def test_admin_can_grant_list_and_revoke(client_factory) -> None:
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = str(uuid.uuid4())

    created = client.post(
        "/api/v1/access/grants", json={"subject_id": subject, "permission": "notes.delete"}
    )
    assert created.status_code == 201
    grant_id = created.json()["id"]

    listed = client.get("/api/v1/access/grants", params={"subject_id": subject}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["permission"] == "notes.delete"

    assert client.delete(f"/api/v1/access/grants/{grant_id}").status_code == 204
    assert client.get("/api/v1/access/grants", params={"subject_id": subject}).json()["total"] == 0


def test_a_non_admin_cannot_manage_grants(client_factory) -> None:
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
    response = client.post(
        "/api/v1/access/grants", json={"subject_id": str(uuid.uuid4()), "permission": "x.y"}
    )
    assert response.status_code == 403


def test_granting_an_undeclared_permission_is_refused_with_the_catalog(
    client_factory,
) -> None:
    """A grant of a string this app never checks is a no-op, so it is refused.

    `terp grant add` has refused this since ADR 0089 and printed the catalog; the
    endpoint now makes the same check and returns the catalog as `details`, which is
    what lets a permission editor offer the real choices instead of asking someone to
    retype a name it has already rejected.
    """
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = str(uuid.uuid4())

    refused = client.post(
        "/api/v1/access/grants",
        json={"subject_id": subject, "permission": "notes.delelte"},
    )
    assert refused.status_code == 400
    body = refused.json()
    assert body["code"] == "validation_failed"
    details = body["details"]
    assert {"code": "undeclared_permission", "loc": "permission", "msg": "notes.delelte"} in details
    # The catalog rides along, each entry annotated with the role floor it needs.
    assert {
        "code": "declared_permission",
        "loc": "notes.delete",
        "msg": "needs role editor or higher",
    } in details
    # Refused means refused: nothing was stored.
    assert client.get(
        "/api/v1/access/grants", params={"subject_id": subject}
    ).json()["total"] == 0


def test_deleting_a_note_needs_the_grant_on_top_of_the_write_tier(
    client_factory, db_session: Session
) -> None:
    """`notes` reads and writes on the role tier; deleting needs `notes.delete` too.

    The first real consumer of a named permission in this repository. An EDITOR may
    create and edit a note through the module's `Policy` alone — destroying one is a
    separate decision the tier cannot express, so it takes a grant as well.
    """
    editor = uuid.uuid4()
    client = client_factory(Principal(id=editor, role=Roles.EDITOR))
    note = client.post("/api/v1/notes/", json={"title": "Deletable", "body": ""})
    assert note.status_code == 201
    note_id = note.json()["id"]

    # Writing is allowed by the tier; deleting is not, without the grant.
    assert client.patch(
        f"/api/v1/notes/{note_id}",
        json={"title": "Edited by an editor", "version": note.json()["version"]},
    ).status_code == 200
    assert client.delete(f"/api/v1/notes/{note_id}").status_code == 403

    AccessService().grant(db_session, editor, "notes.delete")
    db_session.commit()
    assert client.delete(f"/api/v1/notes/{note_id}").status_code == 204
    assert client.get(f"/api/v1/notes/{note_id}").status_code == 404


def test_an_unauthenticated_caller_cannot_read_grants(client_factory) -> None:
    client = client_factory(None)
    response = client.get("/api/v1/access/grants", params={"subject_id": str(uuid.uuid4())})
    assert response.status_code == 401
