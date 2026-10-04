"""End-to-end: audit is auto-emitted from the BaseService chokepoint with zero wiring.

Proves the Phase-D promise (ADR 0007): a module author writes **no** audit code,
yet every mutation through ``BaseService`` (flat ``notes`` and the ``tasks``
soft-delete alike) lands an append-only audit row carrying the action, the target,
the acting principal, and the request correlation id — readable through the
self-registered, admin-only ``audit`` log.
"""

from __future__ import annotations

import uuid

from terp.core import Principal, Roles


def _admin(client_factory):
    return client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))


def test_a_mutation_auto_emits_an_audit_row(client_factory, editor) -> None:
    created = client_factory(editor).post(
        "/api/v1/notes/", json={"title": "audited", "body": "hi"}
    ).json()

    listing = _admin(client_factory).get("/api/v1/audit/")
    assert listing.status_code == 200, listing.text
    events = [e for e in listing.json()["items"] if e["target_type"] == "Note"]
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "created"
    assert event["target_id"] == created["id"]
    # The actor is captured from the request principal, with zero module wiring.
    assert event["actor_id"] == str(editor.id)
    # The request correlation id rides along for tracing.
    assert event["request_id"]


def test_update_and_soft_delete_are_audited(client_factory, editor) -> None:
    editor_client = client_factory(editor)
    task = editor_client.post("/api/v1/tasks/", json={"title": "t"}).json()
    editor_client.patch(
        f"/api/v1/tasks/{task['id']}", json={"status": "done", "version": 1}
    )
    # tasks overrides delete (soft delete) but routes through the audited _save hook.
    editor_client.delete(f"/api/v1/tasks/{task['id']}")

    events = _admin(client_factory).get("/api/v1/audit/").json()["items"]
    actions = {(e["target_type"], e["action"]) for e in events if e["target_type"] == "Task"}
    assert actions == {("Task", "created"), ("Task", "updated"), ("Task", "deleted")}


def test_audit_log_is_admin_only(client_factory, editor, viewer) -> None:
    # The trail is privileged: a non-admin (even an editor) cannot read it.
    assert client_factory(editor).get("/api/v1/audit/").status_code == 403
    denied = client_factory(viewer).get("/api/v1/audit/")
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


def test_audit_list_is_paginated(client_factory, editor) -> None:
    editor_client = client_factory(editor)
    for i in range(3):
        editor_client.post("/api/v1/notes/", json={"title": f"n{i}"})

    page = _admin(client_factory).get("/api/v1/audit/", params={"limit": 2})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2


def test_activity_counts_a_mutation_on_todays_date_in_the_requested_zone(
    client_factory, editor
) -> None:
    client_factory(editor).post("/api/v1/notes/", json={"title": "counted"})

    response = _admin(client_factory).get(
        "/api/v1/audit/activity", params={"days": 7, "time_zone": "Europe/Amsterdam"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["time_zone"] == "Europe/Amsterdam"
    assert len(body["days"]) == 7
    assert len(body["previous_days"]) == 7
    # Oldest first, ending today, so the mutation just made is on the last day.
    assert body["days"][-1]["count"] >= 1
    assert body["total"] == sum(day["count"] for day in body["days"])
    assert {"action": "created", "count": 1} in body["by_action"]
    assert {"target_type": "Note", "count": 1} in body["by_target_type"]


def test_activity_is_admin_only(client_factory, editor) -> None:
    denied = client_factory(editor).get("/api/v1/audit/activity")
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


def test_activity_refuses_a_time_zone_it_does_not_know(client_factory) -> None:
    admin = _admin(client_factory)
    unknown = admin.get("/api/v1/audit/activity", params={"time_zone": "Mars/Olympus"})
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "validation_failed"
    # A name shaped like a path never reaches the zone database.
    assert admin.get("/api/v1/audit/activity", params={"time_zone": "../etc"}).status_code == 422


def test_activity_counts_between_one_and_ninety_days(client_factory) -> None:
    admin = _admin(client_factory)
    assert admin.get("/api/v1/audit/activity", params={"days": 0}).status_code == 422
    assert admin.get("/api/v1/audit/activity", params={"days": 91}).status_code == 422
    assert len(admin.get("/api/v1/audit/activity", params={"days": 90}).json()["days"]) == 90
