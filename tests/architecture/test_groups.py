"""The groups capability: audited membership algebra + group-aware permission checks.

Three layers are proven here:

* the :class:`GroupsService` algebra — audited CRUD, idempotent membership,
  404s for unknown groups / non-members, and the atomic delete cascade
  (memberships and the group's grants go with the group, in one transaction);
* the access **subject-expansion seam** — registration is idempotent, a grant
  to a group is effective for members through ``AccessService.has_permission``
  / ``permissions_for``, and a failing expander fails closed (propagates);
* the guard integration — a ``require_permission``-gated route allows a group
  member and refuses everyone else, end-to-end through ``create_app``.
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

from terp.core import (
    ConflictError,
    ModuleSpec,
    NotFoundError,
    Policy,
    Roles,
    create_app,
    get_session,
)
from terp.core.audit import AuditAction, AuditRecord, set_audit_sink

from terp.capabilities.access import (
    AccessService,
    register_subject_expander,
    require_permission,
    reset_subject_expanders,
    subject_ids_for,
)
from terp.capabilities.auth import create_access_token
from terp.capabilities.auth import get_principal as auth_get_principal
from terp.capabilities.groups import (
    GroupCreate,
    GroupUpdate,
    GroupsService,
    expand_group_memberships,
    register_group_expansion,
)


@pytest.fixture(autouse=True)
def _canonical_expanders() -> Iterator[None]:
    """Restore the process-global expander registry to its canonical state.

    Tests below register throwaway expanders / reset the registry; afterwards the
    registry must hold exactly the groups expander again (other suites rely on it).
    """
    yield
    reset_subject_expanders()
    register_group_expansion()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()


def _capture_audit() -> list[AuditRecord]:
    records: list[AuditRecord] = []
    set_audit_sink(lambda _session, record, _policy: records.append(record))
    return records


# --- the service: audited CRUD + membership algebra -------------------------- #


def test_group_crud_is_audited_and_occ_guarded(session: Session) -> None:
    records = _capture_audit()
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance", description="money"))
    updated = service.update(
        session, group.id, GroupUpdate(name="Finance EU", version=group.version)
    )
    assert updated.name == "Finance EU"
    assert updated.description == "money"  # partial patch keeps the rest
    assert [record.action for record in records] == [
        AuditAction.CREATED,
        AuditAction.UPDATED,
    ]
    assert all(record.target_type == "Group" for record in records)


def test_duplicate_group_name_maps_to_conflict(session: Session) -> None:
    service = GroupsService()
    service.create(session, GroupCreate(name="Finance"))
    with pytest.raises(ConflictError):
        service.create(session, GroupCreate(name="Finance"))


def test_membership_is_idempotent_and_audited(session: Session) -> None:
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance"))
    records = _capture_audit()
    user = uuid.uuid4()
    first = service.add_member(session, group.id, user)
    again = service.add_member(session, group.id, user)
    assert first.id == again.id
    assert [record.action for record in records] == [AuditAction.CREATED]
    assert records[0].target_type == "GroupMember"


def test_membership_of_an_unknown_group_is_not_found(session: Session) -> None:
    service = GroupsService()
    with pytest.raises(NotFoundError):
        service.add_member(session, uuid.uuid4(), uuid.uuid4())
    with pytest.raises(NotFoundError):
        service.members_for(session, uuid.uuid4(), skip=0, limit=10)


def test_removing_a_non_member_is_not_found(session: Session) -> None:
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance"))
    with pytest.raises(NotFoundError):
        service.remove_member(session, group.id, uuid.uuid4())


def test_members_listing_paginates_one_group_only(session: Session) -> None:
    service = GroupsService()
    finance = service.create(session, GroupCreate(name="Finance"))
    ops = service.create(session, GroupCreate(name="Ops"))
    users = [uuid.uuid4() for _ in range(3)]
    for user in users:
        service.add_member(session, finance.id, user)
    service.add_member(session, ops.id, uuid.uuid4())
    rows, total = service.members_for(session, finance.id, skip=0, limit=2)
    assert total == 3
    assert len(rows) == 2
    assert all(row.group_id == finance.id for row in rows)


def test_member_counts_come_back_grouped(session: Session) -> None:
    service = GroupsService()
    finance = service.create(session, GroupCreate(name="Finance"))
    ops = service.create(session, GroupCreate(name="Ops"))
    for _ in range(2):
        service.add_member(session, finance.id, uuid.uuid4())
    assert service.member_counts(session, []) == {}
    counts = service.member_counts(session, [finance.id, ops.id])
    assert counts.get(finance.id) == 2
    assert counts.get(ops.id) in (None, 0)


# --- delete cascade: memberships + grants go with the group, atomically ------ #


def test_deleting_a_group_cascades_members_and_grants(session: Session) -> None:
    service = GroupsService()
    access = AccessService()
    group = service.create(session, GroupCreate(name="Finance"))
    member = uuid.uuid4()
    service.add_member(session, group.id, member)
    access.grant(session, group.id, "reports:export")
    assert access.has_permission(session, member, "reports:export")

    records = _capture_audit()
    service.delete(session, group.id)

    with pytest.raises(NotFoundError):
        service.get(session, group.id)
    assert service.group_ids_for(session, member) == set()
    assert access.permissions_for(session, group.id) == set()
    assert access.has_permission(session, member, "reports:export") is False
    # One atomic unit: the group's DELETED record, then the cascaded rows'.
    assert [record.target_type for record in records] == [
        "Group",
        "GroupMember",
        "Grant",
    ]
    assert all(record.action is AuditAction.DELETED for record in records)


def test_a_failing_cascade_rolls_back_the_whole_delete(session: Session) -> None:
    """If any cascaded write fails, the group delete fails with it — no half-delete."""
    service = GroupsService()
    access = AccessService()
    group = service.create(session, GroupCreate(name="Finance"))
    member = uuid.uuid4()
    service.add_member(session, group.id, member)
    access.grant(session, group.id, "reports:export")

    def _sink(_session: Session, record: AuditRecord, _policy: object) -> None:
        if record.target_type == "Grant":  # the last cascaded write
            raise RuntimeError("audit store down")

    set_audit_sink(_sink)
    with pytest.raises(RuntimeError):
        service.delete(session, group.id)

    set_audit_sink(lambda _session, _record, _policy: None)
    session.rollback()
    assert service.get(session, group.id).id == group.id
    assert service.group_ids_for(session, member) == {group.id}
    assert access.has_permission(session, member, "reports:export")


def test_the_cascade_drains_past_the_batch_size(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A group larger than one cascade batch is drained completely — no size cliff.

    The cascade loops in batches; memberships and grants beyond a single batch
    must go with the group (an orphaned grant on a dead subject id would linger
    invisibly), so this pins the loop with a tiny batch and 3x-batch rows.
    """
    import terp.capabilities.groups.service as groups_service

    monkeypatch.setattr(groups_service, "_CASCADE_BATCH", 2)
    service = GroupsService()
    access = AccessService()
    group = service.create(session, GroupCreate(name="Big"))
    members = [uuid.uuid4() for _ in range(5)]
    for member in members:
        service.add_member(session, group.id, member)
    for index in range(5):
        access.grant(session, group.id, f"perm:{index}")

    service.delete(session, group.id)

    with pytest.raises(NotFoundError):
        service.get(session, group.id)
    for member in members:
        assert service.group_ids_for(session, member) == set()
    assert access.permissions_for(session, group.id) == set()


# --- the expansion seam ------------------------------------------------------ #


def test_registration_is_idempotent(session: Session) -> None:
    register_group_expansion()
    register_group_expansion()
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance"))
    member = uuid.uuid4()
    service.add_member(session, group.id, member)
    # One expander, so the set is exactly the subject + its groups (no dupes).
    assert subject_ids_for(session, member) == {member, group.id}


def test_a_group_id_expands_to_nothing(session: Session) -> None:
    """Expansion is flat: a group is never a member, so its id expands to itself only."""
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance"))
    assert subject_ids_for(session, group.id) == {group.id}
    assert list(expand_group_memberships(session, group.id)) == []


def test_a_failing_expander_fails_closed(session: Session) -> None:
    """An expander that raises propagates — the check never narrows silently."""

    def _broken(_session: Session, _subject: uuid.UUID) -> list[uuid.UUID]:
        raise RuntimeError("membership store down")

    register_subject_expander(_broken)
    with pytest.raises(RuntimeError):
        AccessService().has_permission(session, uuid.uuid4(), "anything")


def test_reset_clears_the_registry(session: Session) -> None:
    reset_subject_expanders()
    service = GroupsService()
    group = service.create(session, GroupCreate(name="Finance"))
    member = uuid.uuid4()
    service.add_member(session, group.id, member)
    assert subject_ids_for(session, member) == {member}


# --- the guard: a group grant authorizes members end-to-end ------------------ #


@pytest.fixture
def gated_app() -> Iterator[tuple[FastAPI, Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    gated = APIRouter(tags=["gated"])

    @gated.post(
        "/act",
        response_model=str,
        dependencies=[Depends(require_permission("widgets:write"))],
    )
    async def act() -> str:
        return "ok"

    spec = ModuleSpec(
        name="gated",
        router=gated,
        policy=Policy.public_write(
            reason="action is gated by a fine-grained grant, not a role"
        ),
    )
    application = create_app([spec], principal_provider=auth_get_principal)

    def _session_override() -> Iterator[Session]:
        with Session(engine) as active:
            yield active

    application.dependency_overrides[get_session] = _session_override
    try:
        yield application, engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def _bearer(app: FastAPI, subject: uuid.UUID) -> TestClient:
    client = TestClient(app)
    token = create_access_token(subject=subject, role=Roles.EDITOR)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_a_group_grant_authorizes_members_and_only_members(
    gated_app: tuple[FastAPI, Engine],
) -> None:
    app, engine = gated_app
    member, outsider = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as setup:
        service = GroupsService()
        group = service.create(setup, GroupCreate(name="Widget makers"))
        group_id = group.id
        service.add_member(setup, group_id, member)
        AccessService().grant(setup, group_id, "widgets:write")

    assert _bearer(app, member).post("/api/v1/gated/act").status_code == 200
    assert _bearer(app, outsider).post("/api/v1/gated/act").status_code == 403

    with Session(engine) as setup:
        GroupsService().remove_member(setup, group_id, member)
    assert _bearer(app, member).post("/api/v1/gated/act").status_code == 403
