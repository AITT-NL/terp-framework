"""End-to-end slice: visibility-based read scope on ``journals`` (ADR 0061).

The second divergent consumer of the row-scope registry (ADR 0017; tenancy is the
first): a consumer-registered predicate hides another owner's ``private`` journals
from every read path — detail 404s, lists omit — while ``shared`` rows (the default)
stay readable by anyone the role policy admits. The owner always sees their own rows.
No module read code changed: the predicate composes inside ``BaseService.base_query``
exactly like the tenant filter, proving the kernel seam is strategy-agnostic.
"""

from __future__ import annotations

import uuid

from terp.core import Principal, Roles

from app.modules.journals.models import Journal
from app.modules.journals.service import JournalService


def _other_editor(client_factory):
    return client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))


def test_default_visibility_is_shared_and_readable_by_non_owner(
    client_factory, editor
) -> None:
    owner = client_factory(editor)
    created = owner.post("/api/v1/journals/", json={"title": "Open", "entry": "hi"})
    assert created.status_code == 201, created.text
    assert created.json()["visibility"] == "shared"

    reader = _other_editor(client_factory)
    assert reader.get(f"/api/v1/journals/{created.json()['id']}").status_code == 200


def test_private_journal_is_hidden_from_non_owner_reads(client_factory, editor) -> None:
    owner = client_factory(editor)
    created = owner.post(
        "/api/v1/journals/",
        json={"title": "Diary", "entry": "secret", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    journal_id = created.json()["id"]

    # The owner still sees their private row — detail and list.
    assert owner.get(f"/api/v1/journals/{journal_id}").status_code == 200
    assert journal_id in {j["id"] for j in owner.get("/api/v1/journals/").json()["items"]}

    # A different EDITOR clears the coarse role policy, but the row is scoped away:
    # the detail read 404s (not 403 — the row does not exist for this caller) and
    # the list omits it. Fail closed, with zero module read code.
    intruder = _other_editor(client_factory)
    assert intruder.get(f"/api/v1/journals/{journal_id}").status_code == 404
    assert journal_id not in {
        j["id"] for j in intruder.get("/api/v1/journals/").json()["items"]
    }


def test_owner_can_flip_visibility_and_the_scope_follows(client_factory, editor) -> None:
    owner = client_factory(editor)
    journal_id = owner.post(
        "/api/v1/journals/", json={"title": "Draft", "entry": "wip"}
    ).json()["id"]
    reader = _other_editor(client_factory)
    assert reader.get(f"/api/v1/journals/{journal_id}").status_code == 200

    hidden = owner.patch(
        f"/api/v1/journals/{journal_id}", json={"visibility": "private", "version": 1}
    )
    assert hidden.status_code == 200, hidden.text
    assert reader.get(f"/api/v1/journals/{journal_id}").status_code == 404

    # And back: sharing again restores the non-owner read.
    shared = owner.patch(
        f"/api/v1/journals/{journal_id}", json={"visibility": "shared", "version": 2}
    )
    assert shared.status_code == 200, shared.text
    assert reader.get(f"/api/v1/journals/{journal_id}").status_code == 200


def test_unknown_visibility_value_never_widens_reads(client_factory, editor) -> None:
    # Anything other than the literal "shared" is owner-only: the predicate matches
    # the shared value, so a typo'd or novel state fails closed instead of leaking.
    owner = client_factory(editor)
    journal_id = owner.post(
        "/api/v1/journals/",
        json={"title": "Odd", "entry": "x", "visibility": "unlisted"},
    ).json()["id"]

    assert owner.get(f"/api/v1/journals/{journal_id}").status_code == 200
    assert _other_editor(client_factory).get(
        f"/api/v1/journals/{journal_id}"
    ).status_code == 404


def test_unbound_actor_does_not_match_unowned_private_journals(db_session) -> None:
    journal = Journal(title="System private", entry="x", visibility="private")
    db_session.add(journal)
    db_session.commit()

    rows, total = JournalService().list(db_session, skip=0, limit=100)
    assert total == 0
    assert rows == []


def test_visibility_scope_does_not_leak_onto_other_models(client_factory, editor) -> None:
    # Two divergent strategies coexist on the one registry: the journals predicate
    # guards on its own model, so an unrelated module's reads are untouched by it.
    client = client_factory(editor)
    note_id = client.post(
        "/api/v1/notes/", json={"title": "n", "body": "b"}
    ).json()["id"]
    assert _other_editor(client_factory).get(f"/api/v1/notes/{note_id}").status_code == 200
