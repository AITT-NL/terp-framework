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


def test_the_access_model_is_served_to_an_admin_and_refused_to_everyone_else(
    client_factory,
) -> None:
    """`GET /model` is the read half of a permission editor, and it is admin-only.

    The permission topology is a map of where the doors are, so an under-privileged caller
    should not be able to enumerate it. A caller asking what *they themselves* may do is a
    different question, answered by `GET /me` (ADR 0096), which needs no privilege because
    it only ever reports the caller's own.
    """
    admin = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    model = admin.get("/api/v1/access/model")
    assert model.status_code == 200
    body = model.json()

    # The ladder comes from the app's own PermissionModel, rank-ascending.
    assert [role["name"] for role in body["roles"]] == ["viewer", "editor", "admin"]
    # The catalog carries the label, which is the text a pane puts beside the row.
    assert body["permissions"] == [
        {
            "name": "notes.delete",
            "min_role": "editor",
            "label": "Delete a note someone else wrote",
        }
    ]

    notes = next(module for module in body["modules"] if module["name"] == "notes")
    assert notes["access"] == {
        "assignable": True,
        "label": "Notes",
        "platform_reason": None,
    }
    assert notes["permissions"] == ["notes.delete"]

    # The route that needs the grant reports every rung as needing it: the module policy
    # lets an editor write, and the route-level requirement is the second gate. A pane that
    # showed `allowed` here would be disagreeing with the guard.
    delete = next(
        endpoint
        for endpoint in notes["endpoints"]
        if endpoint["methods"] == ["DELETE"]
    )
    assert delete["extra_permissions"] == ["notes.delete"]
    assert delete["operation"] == {"id": "notes.delete_note", "label": "Delete a note"}
    assert delete["by_role"] == [
        {"role": "viewer", "allowed": False, "reason": "rank"},
        {"role": "editor", "allowed": False, "reason": "grant"},
        {"role": "admin", "allowed": False, "reason": "grant"},
    ]

    # The platform's own modules say they are never per-module assignable (ADR 0121).
    users = next(module for module in body["modules"] if module["name"] == "users")
    assert users["access"]["assignable"] is False
    assert users["access"]["platform_reason"]

    assert (
        client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
        .get("/api/v1/access/model")
        .status_code
        == 403
    )
    assert client_factory(None).get("/api/v1/access/model").status_code == 401


def test_the_subject_endpoint_says_where_every_right_came_from(
    client_factory, make_user, db_session: Session
) -> None:
    """"Why can this person do that?" — the question that makes the rest of this safe.

    A matrix of effective answers cannot answer it: it can say someone may delete a note and
    not that they may because of a group somebody added them to in March. So every row names
    the subject it came from, and where several module rows exist for one module only the
    highest is marked effective — which is the thing most often misread, because assigning a
    lower rung alongside a higher one changes nothing at all.
    """
    from terp.capabilities.access import ModuleRoleService
    from terp.capabilities.groups import GroupsService
    from terp.capabilities.groups.schemas import GroupCreate

    admin = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    member = make_user("provenance@acme.test", "correct horse battery staple")

    groups = GroupsService()
    group = groups.create(db_session, GroupCreate(name="Note keepers"))
    groups.add_member(db_session, group.id, member)

    # The grant is held by the *group*, not the person.
    AccessService().grant(db_session, group.id, "notes.delete")
    # Two rungs in one module: the higher one is what actually decides.
    roles = ModuleRoleService()
    roles.assign(db_session, member, "notes", int(Roles.VIEWER))
    roles.assign(db_session, group.id, "notes", int(Roles.EDITOR))

    body = admin.get(f"/api/v1/access/subjects/{member}").json()

    assert body["subject_id"] == str(member)
    # The expanded set is reported, and the group is *named* — which is what the attributed
    # expander bought: before it, a report could only show the group's id.
    assert {(ref["kind"], ref["name"]) for ref in body["via"]} == {
        ("self", None),
        ("group", "Note keepers"),
    }

    (permission,) = body["permissions"]
    assert permission["name"] == "notes.delete"
    assert permission["label"] == "Delete a note someone else wrote"
    assert permission["declared"] is True
    assert permission["via"]["name"] == "Note keepers"  # not held directly

    # Both rungs are shown; exactly one is effective, and it is the group's.
    assert [(r["role"], r["effective"], r["via"]["kind"]) for r in body["module_roles"]] == [
        ("editor", True, "group"),
        ("viewer", False, "self"),
    ]
    assert all(row["stale"] == [] for row in body["module_roles"])


def test_the_subject_endpoint_shows_a_stale_right_rather_than_hiding_it(
    client_factory, make_user, db_session: Session
) -> None:
    """A filtered row is a right nobody can explain, so nothing is filtered.

    Both stale shapes at once: a grant naming a permission the app does not declare, and a
    module role in a module that never opted in. These are exactly the rows an administrator
    is hunting for when something looks wrong, and the ones a tidy-looking view would drop.
    """
    from terp.capabilities.access import ModuleRoleService

    admin = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = make_user("stale@acme.test", "correct horse battery staple")

    AccessService().grant(db_session, subject, "retired.capability")
    ModuleRoleService().assign(db_session, subject, "tasks", int(Roles.EDITOR))

    body = admin.get(f"/api/v1/access/subjects/{subject}").json()

    (permission,) = body["permissions"]
    assert permission["name"] == "retired.capability"
    assert permission["declared"] is False
    assert permission["label"] is None

    (role,) = body["module_roles"]
    assert role["module"] == "tasks"
    assert role["stale"] == ["this app no longer declares the module assignable"]
    # Still reported as effective: it is the highest row for that module, and whether it
    # *applies* is what `stale` says. Conflating the two would hide one of the two facts.
    assert role["effective"] is True


def test_the_subject_endpoint_is_admin_only(client_factory) -> None:
    subject = uuid.uuid4()
    assert (
        client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
        .get(f"/api/v1/access/subjects/{subject}")
        .status_code
        == 403
    )
    assert (
        client_factory(None).get(f"/api/v1/access/subjects/{subject}").status_code == 401
    )


def test_an_unauthenticated_caller_cannot_read_grants(client_factory) -> None:
    client = client_factory(None)
    response = client.get("/api/v1/access/grants", params={"subject_id": str(uuid.uuid4())})
    assert response.status_code == 401


# --- the module-role writer: assignment as an in-app administration surface -- #
# ADR 0121 §6 puts assignment on the HTTP surface while granting stays an operator command,
# because none of ADR 0089's three costs — an admin token, a UUID, an undiscoverable string —
# applies to an administrator picking a declared rung for a named person. The service algebra
# these routes sit on is proven in `tests/architecture/test_module_roles.py`; what follows is
# the wiring only: that the routes are addressed by the pair, refuse through the same
# validation the command uses, and are admin-only.
MODULE_ROLE_URL = "/api/v1/access/subjects/{subject}/module-roles/{module}"


def test_assigning_a_rung_is_addressed_by_the_pair_and_updates_one_fact(
    client_factory,
) -> None:
    """A second PUT at a different rank changes the row it already found.

    The reason the route is a ``PUT`` on ``(subject, module)`` rather than a ``POST``: that
    pair is the fact's identity, so "make it editor here" must be expressible without first
    reading whether a row exists. A ``POST`` that quietly updated would be a create that is
    not one; a ``POST`` that appended would leave two rows for one question.
    """
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = str(uuid.uuid4())
    url = MODULE_ROLE_URL.format(subject=subject, module="notes")

    first = client.put(url, json={"role_rank": 10})
    assert first.status_code == 200
    assert first.json()["role_rank"] == 10

    # Raised, not appended. The id is the observation: a second row would carry a new one,
    # and the pane would then have two answers to "what does this person hold in notes?".
    raised = client.put(url, json={"role_rank": 20})
    assert raised.status_code == 200
    assert raised.json()["role_rank"] == 20
    assert raised.json()["id"] == first.json()["id"]

    held = client.get(f"/api/v1/access/subjects/{subject}").json()["module_roles"]
    assert [(row["module"], row["role_rank"], row["effective"]) for row in held] == [
        ("notes", 20, True)
    ]


def test_revoking_a_rung_is_safe_when_there_is_nothing_to_revoke(client_factory) -> None:
    """204 either way, because a retry of a successful revoke is not a failure.

    And no catalog check on the way out: a module the app has stopped declaring assignable is
    exactly the assignment that most needs clearing, so validating here would strand it.
    """
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = str(uuid.uuid4())
    url = MODULE_ROLE_URL.format(subject=subject, module="notes")

    assert client.put(url, json={"role_rank": 20}).status_code == 200
    assert client.delete(url).status_code == 204
    assert client.get(f"/api/v1/access/subjects/{subject}").json()["module_roles"] == []
    # Already gone, and still 204 — a 404 here would make an idempotent retry look broken.
    assert client.delete(url).status_code == 204


def test_the_writer_refuses_what_the_declarations_do_not_support(client_factory) -> None:
    """The endpoint refuses through the same check ``terp module-role add`` makes.

    Three refusals with three different fixes, and the endpoint's job is to be on the same
    side of each as the command: a module that administers the platform's own authority, a
    module that never opted in, and a rank this app's ladder does not declare. A row stored
    for any of the three could never fire, which is a silent no-op wearing a success code.
    """
    client = client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))
    subject = str(uuid.uuid4())

    # `access` itself: never assignable, and it says why rather than only saying no.
    platform = client.put(
        MODULE_ROLE_URL.format(subject=subject, module="access"),
        json={"role_rank": 30},
    )
    assert platform.status_code == 400
    assert "never per-module assignable" in platform.json()["detail"]

    unopted = client.put(
        MODULE_ROLE_URL.format(subject=subject, module="health"),
        json={"role_rank": 20},
    )
    assert unopted.status_code == 400
    assert "has not opted into" in unopted.json()["detail"]
    # Naming what *is* assignable is the difference between a refusal and a dead end.
    assert "notes" in unopted.json()["detail"]

    undeclared = client.put(
        MODULE_ROLE_URL.format(subject=subject, module="notes"),
        json={"role_rank": 25},
    )
    assert undeclared.status_code == 400
    assert "declares no role at rank 25" in undeclared.json()["detail"]

    # And none of the three left a row behind.
    assert client.get(f"/api/v1/access/subjects/{subject}").json()["module_roles"] == []


def test_only_an_admin_may_assign_or_revoke_a_rung(client_factory) -> None:
    """The module's own ``Policy`` gates this: handing out authority is a privileged act.

    An editor being able to give itself ``admin`` in one module would make the per-module
    ladder a way around the global one rather than a refinement of it.
    """
    subject = uuid.uuid4()
    url = MODULE_ROLE_URL.format(subject=subject, module="notes")

    editor = client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
    assert editor.put(url, json={"role_rank": 20}).status_code == 403
    assert editor.delete(url).status_code == 403

    anonymous = client_factory(None)
    assert anonymous.put(url, json={"role_rank": 20}).status_code == 401
    assert anonymous.delete(url).status_code == 401
