"""End-to-end slice: the ``notes`` module over packaged ``terp.core``.

Validates that the narrow kernel is sufficient to build a real secure CRUD
module: OCC, pagination, the error envelope, and deny-by-default authz all work
end-to-end with only ``terp.core`` + a thin app composition.
"""

from __future__ import annotations

import uuid

import pytest

from terp.core import BootError, ModuleSpec, Principal, Roles, create_app


def test_create_and_get(client_factory, editor) -> None:
    client = client_factory(editor)
    response = client.post("/api/v1/notes/", json={"title": "First", "body": "hello"})
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["title"] == "First"
    assert created["version"] == 1

    fetched = client.get(f"/api/v1/notes/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_list_is_paginated(client_factory, editor) -> None:
    client = client_factory(editor)
    for i in range(3):
        client.post("/api/v1/notes/", json={"title": f"n{i}"})

    response = client.get("/api/v1/notes/", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2


def test_get_missing_returns_404_envelope(client_factory, editor) -> None:
    client = client_factory(editor)
    response = client.get(f"/api/v1/notes/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert set(body) == {"code", "detail", "request_id"}


def test_update_increments_version(client_factory, editor) -> None:
    client = client_factory(editor)
    created = client.post("/api/v1/notes/", json={"title": "v"}).json()
    response = client.patch(
        f"/api/v1/notes/{created['id']}", json={"title": "v2", "version": 1}
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["title"] == "v2"


def test_stale_update_conflicts(client_factory, editor) -> None:
    client = client_factory(editor)
    created = client.post("/api/v1/notes/", json={"title": "x"}).json()
    note_id = created["id"]
    # First update succeeds (version 1 -> 2).
    first = client.patch(f"/api/v1/notes/{note_id}", json={"title": "y", "version": 1})
    assert first.status_code == 200
    # Re-using the now-stale version 1 is rejected (optimistic concurrency).
    stale = client.patch(f"/api/v1/notes/{note_id}", json={"title": "z", "version": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_data"


def test_actor_stamps_capture_creator_and_last_editor(client_factory, editor) -> None:
    # Created by the editor: both stamps carry the acting principal, with zero wiring.
    created = client_factory(editor).post("/api/v1/notes/", json={"title": "p"}).json()
    assert created["created_by_id"] == str(editor.id)
    assert created["modified_by_id"] == str(editor.id)

    # A different editor updates it: created_by is preserved, modified_by advances to the
    # latest writer — provenance the module never wired by hand.
    other = Principal(id=uuid.uuid4(), role=Roles.EDITOR)
    updated = client_factory(other).patch(
        f"/api/v1/notes/{created['id']}", json={"title": "p2", "version": 1}
    ).json()
    assert updated["created_by_id"] == str(editor.id)
    assert updated["modified_by_id"] == str(other.id)


def test_unauthenticated_is_denied(client_factory) -> None:
    client = client_factory(None)
    response = client.get("/api/v1/notes/")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_viewer_cannot_mutate(client_factory, viewer) -> None:
    client = client_factory(viewer)
    assert client.get("/api/v1/notes/").status_code == 200
    response = client.post("/api/v1/notes/", json={"title": "nope"})
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_deny_by_default_boots_closed_without_policy() -> None:
    spec = ModuleSpec(name="broken")  # no Policy declared
    with pytest.raises(BootError):
        create_app([spec])
