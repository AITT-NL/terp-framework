"""End-to-end slice: object-level (ownership) authorization on the ``journals`` module.

Proves the per-row write gate (ADR 0029) over the real composition: the owner of a
journal entry may read, edit, and delete it, but a **different** principal who clears
the *same* coarse role policy (both are EDITORs) cannot edit or delete it — a non-owner
``PATCH`` / ``DELETE`` is refused 403. A read is still permitted, demonstrating that
this seam gates *writes* (read visibility is the separate scope-registry seam, ADR
0017). The coarse role floor still applies underneath: a VIEWER cannot write at all.
"""

from __future__ import annotations

import uuid

from terp.core import Principal, Roles


def test_owner_can_create_read_update_and_delete(client_factory, editor) -> None:
    client = client_factory(editor)
    created = client.post(
        "/api/v1/journals/", json={"title": "Day 1", "entry": "hello"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # The creator is stamped as the owner, with zero module wiring.
    assert body["owner_id"] == str(editor.id)
    journal_id = body["id"]

    assert client.get(f"/api/v1/journals/{journal_id}").status_code == 200

    updated = client.patch(
        f"/api/v1/journals/{journal_id}", json={"title": "Day 1 (edited)", "version": 1}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Day 1 (edited)"

    assert client.delete(f"/api/v1/journals/{journal_id}").status_code == 204
    assert client.get(f"/api/v1/journals/{journal_id}").status_code == 404


def test_non_owner_cannot_modify_but_can_read(client_factory, editor) -> None:
    owner = client_factory(editor)
    created = owner.post(
        "/api/v1/journals/", json={"title": "Private", "entry": "secret"}
    ).json()
    journal_id = created["id"]

    # A *different* EDITOR: clears the coarse write policy, but is not the owner.
    intruder = client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))

    # Reads are not owner-gated (visibility is the scope-registry seam, ADR 0017).
    assert intruder.get(f"/api/v1/journals/{journal_id}").status_code == 200

    # Writes are: the per-row ownership gate denies a non-owner update and delete.
    patched = intruder.patch(
        f"/api/v1/journals/{journal_id}", json={"title": "tampered", "version": 1}
    )
    assert patched.status_code == 403
    assert patched.json()["code"] == "permission_denied"

    deleted = intruder.delete(f"/api/v1/journals/{journal_id}")
    assert deleted.status_code == 403
    assert deleted.json()["code"] == "permission_denied"

    # The entry is untouched: the denied writes never committed.
    assert owner.get(f"/api/v1/journals/{journal_id}").json()["title"] == "Private"


def test_role_floor_still_applies_under_ownership(client_factory, editor, viewer) -> None:
    # Ownership is layered *on top of* the role gate, not instead of it: a VIEWER is
    # refused a write by the coarse policy before ownership is even consulted.
    owner = client_factory(editor)
    journal_id = owner.post("/api/v1/journals/", json={"title": "x"}).json()["id"]

    response = client_factory(viewer).patch(
        f"/api/v1/journals/{journal_id}", json={"title": "y", "version": 1}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
