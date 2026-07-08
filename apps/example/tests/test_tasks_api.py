"""End-to-end tests for the ``tasks`` module — the divergent behaviours.

The shared concerns (auth, envelope, pagination, OCC) are already proven by the
notes slice; here we focus on what makes ``tasks`` different: soft-delete, the
status filter, and the soft-delete + actor-stamping composition.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from terp.core import Principal, Roles


def test_create_defaults_status_open(client_factory, editor) -> None:
    client = client_factory(editor)
    response = client.post("/api/v1/tasks/", json={"title": "T1"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "open"
    assert body["version"] == 1


def test_list_filters_by_status(client_factory, editor) -> None:
    client = client_factory(editor)
    client.post("/api/v1/tasks/", json={"title": "a", "status": "open"})
    client.post("/api/v1/tasks/", json={"title": "b", "status": "done"})

    response = client.get("/api/v1/tasks/", params={"status": "done"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "done"


def test_soft_delete_hides_task(client_factory, editor) -> None:
    client = client_factory(editor)
    created = client.post("/api/v1/tasks/", json={"title": "x"}).json()
    task_id = created["id"]

    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 204
    # Soft-deleted: no longer fetchable and excluded from the list.
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 404
    listing = client.get("/api/v1/tasks/").json()
    assert listing["total"] == 0
    assert all(item["id"] != task_id for item in listing["items"])


def test_task_optimistic_concurrency_conflict(client_factory, editor) -> None:
    client = client_factory(editor)
    created = client.post("/api/v1/tasks/", json={"title": "x"}).json()
    task_id = created["id"]
    first = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done", "version": 1})
    assert first.status_code == 200
    stale = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "open", "version": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_data"


def test_soft_delete_and_actor_stamping_compose(client_factory, editor, db_engine) -> None:
    # Created by the editor: both stamps carry the acting principal.
    created = client_factory(editor).post("/api/v1/tasks/", json={"title": "x"}).json()
    assert created["created_by_id"] == str(editor.id)
    assert created["modified_by_id"] == str(editor.id)

    # A different principal soft-deletes it.
    remover = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    assert (
        client_factory(remover).delete(f"/api/v1/tasks/{created['id']}").status_code == 204
    )

    # The soft-delete rode the audited _save chokepoint, so the hidden row keeps its
    # provenance: created_by preserved, modified_by = whoever deleted it, deleted_at set.
    from app.modules.tasks.models import Task

    with Session(db_engine) as session:
        row = session.get(Task, uuid.UUID(created["id"]))
    assert row is not None
    assert row.deleted_at is not None
    assert row.created_by_id == editor.id
    assert row.modified_by_id == remover.id
