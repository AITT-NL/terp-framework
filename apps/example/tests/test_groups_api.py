"""End-to-end: the groups capability over the example app's real composition.

The self-registering admin ``groups`` router is discovered and ADMIN-only; the
membership flow works over HTTP; a grant whose subject is a *group* authorizes
members (and stops when membership ends); deleting a group over HTTP cascades
to its memberships and grants; and every mutation lands in the audit trail.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from terp.core import Principal, Roles

from terp.capabilities.access import AccessService


def _admin(client_factory) -> TestClient:
    return client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))


def _create_group(client: TestClient, name: str) -> dict:
    response = client.post(f"{_GROUPS}/", json={"name": name, "description": "demo"})
    assert response.status_code == 201, response.text
    return response.json()


_GROUPS = "/api/v1/groups"


def test_groups_router_is_discovered_and_admin_only(client_factory) -> None:
    admin = _admin(client_factory)
    editor = client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
    anonymous = client_factory(None)
    assert admin.get(f"{_GROUPS}/").status_code == 200
    assert editor.get(f"{_GROUPS}/").status_code == 403
    assert anonymous.get(f"{_GROUPS}/").status_code == 401


def test_group_crud_round_trip(client_factory) -> None:
    admin = _admin(client_factory)
    group = _create_group(admin, "Finance")
    assert group["member_count"] == 0

    listed = admin.get(f"{_GROUPS}/").json()
    assert any(row["id"] == group["id"] for row in listed["items"])

    patched = admin.patch(
        f"{_GROUPS}/{group['id']}",
        json={"description": "money matters", "version": group["version"]},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "money matters"
    assert patched.json()["name"] == "Finance"

    # A stale version is refused (OCC), and a duplicate name conflicts.
    stale = admin.patch(
        f"{_GROUPS}/{group['id']}",
        json={"description": "stale", "version": group["version"]},
    )
    assert stale.status_code == 409
    assert admin.post(f"{_GROUPS}/", json={"name": "Finance"}).status_code == 409


def test_membership_flow_and_counts(client_factory, make_user) -> None:
    admin = _admin(client_factory)
    group = _create_group(admin, "Ops")
    user_id = str(make_user("ops.member@acme.test", "correct horse battery staple"))

    added = admin.post(f"{_GROUPS}/{group['id']}/members", json={"user_id": user_id})
    assert added.status_code == 201
    again = admin.post(f"{_GROUPS}/{group['id']}/members", json={"user_id": user_id})
    assert again.status_code == 201
    assert again.json()["id"] == added.json()["id"]  # idempotent

    members = admin.get(f"{_GROUPS}/{group['id']}/members").json()
    assert [row["user_id"] for row in members["items"]] == [user_id]
    # The listing resolves each member to their account email (no client directory).
    assert members["items"][0]["email"] == "ops.member@acme.test"
    assert admin.get(f"{_GROUPS}/{group['id']}").json()["member_count"] == 1

    removed = admin.delete(f"{_GROUPS}/{group['id']}/members/{user_id}")
    assert removed.status_code == 204
    assert (
        admin.delete(f"{_GROUPS}/{group['id']}/members/{user_id}").status_code == 404
    )
    assert admin.get(f"{_GROUPS}/{group['id']}").json()["member_count"] == 0
    assert admin.get(f"{_GROUPS}/{group['id']}/members").json()["items"] == []


def test_a_group_grant_authorizes_members(
    client_factory, make_user, db_session: Session
) -> None:
    admin = _admin(client_factory)
    group = _create_group(admin, "Report readers")
    member = make_user("report.reader@acme.test", "correct horse battery staple")
    admin.post(f"{_GROUPS}/{group['id']}/members", json={"user_id": str(member)})

    # Granting to the group is an ordinary access grant naming the group's id.
    grant = admin.post(
        "/api/v1/access/grants",
        json={"subject_id": group["id"], "permission": "reports:export"},
    )
    assert grant.status_code == 201

    access = AccessService()
    assert access.has_permission(db_session, member, "reports:export") is True
    admin.delete(f"{_GROUPS}/{group['id']}/members/{member}")
    assert access.has_permission(db_session, member, "reports:export") is False


def test_deleting_a_group_cascades_over_http(
    client_factory, make_user, db_session: Session
) -> None:
    admin = _admin(client_factory)
    group = _create_group(admin, "Doomed")
    member = make_user("doomed.member@acme.test", "correct horse battery staple")
    admin.post(f"{_GROUPS}/{group['id']}/members", json={"user_id": str(member)})
    admin.post(
        "/api/v1/access/grants",
        json={"subject_id": group["id"], "permission": "doomed:permission"},
    )

    assert admin.delete(f"{_GROUPS}/{group['id']}").status_code == 204
    assert admin.get(f"{_GROUPS}/{group['id']}").status_code == 404
    grants = admin.get(
        "/api/v1/access/grants", params={"subject_id": group["id"]}
    ).json()
    assert grants["items"] == []
    assert AccessService().has_permission(
        db_session, member, "doomed:permission"
    ) is False


def test_group_mutations_are_audited(client_factory, make_user) -> None:
    admin = _admin(client_factory)
    group = _create_group(admin, "Audited")
    user_id = str(make_user("audited.member@acme.test", "correct horse battery staple"))
    admin.post(f"{_GROUPS}/{group['id']}/members", json={"user_id": user_id})

    events = admin.get("/api/v1/audit/", params={"limit": 100}).json()["items"]
    actions = {(event["target_type"], event["action"]) for event in events}
    assert ("Group", "created") in actions
    assert ("GroupMember", "created") in actions
