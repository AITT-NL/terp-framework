"""Unit gate for the object-level authorization trait (ADR 0029).

Drives :class:`~terp.core.BaseService` against synthetic owned models over a real
in-memory engine to prove the per-row write gate: an :class:`~terp.core.OwnedMixin`
row gets ``owner_id`` stamped from the request actor on create, the owner may update
and delete it, a **non-owner** update / delete (hard or soft) fails closed with
:class:`~terp.core.PermissionDeniedError`, reads are *not* owner-gated (visibility is
the separate scope-registry seam), and an unowned row / a non-owned model is
unrestricted. It also covers the capability seam — a registered predicate is composed
on top of the built-in owner check and can deny a write — and the registry's reset
seam, exercising the fail-closed / edge paths the end-to-end reference tests do not all
reach, so the framework holds 100% line coverage.

Each logical request runs in its own ``Session`` (as in production), so a denied
write's uncommitted, dirty state is discarded on session close — the same per-request
rollback boundary the runtime write guard relies on (ADR 0015).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    NotFoundError,
    OwnedMixin,
    PermissionDeniedError,
    SoftDeleteMixin,
)
from terp.core.audit import bind_audit_actor
from terp.core.object_authz import (
    apply_object_authz,
    register_object_authz_predicate,
    registered_object_authz_predicates,
    reset_object_authz_predicates,
)


class _OADoc(BaseTable, OwnedMixin, table=True):
    __tablename__ = "_oa_doc"
    label: str = Field(max_length=50)


class _OASoftDoc(BaseTable, SoftDeleteMixin, OwnedMixin, table=True):
    __tablename__ = "_oa_soft_doc"
    label: str = Field(max_length=50)


class _OAPlain(BaseTable, table=True):
    __tablename__ = "_oa_plain"
    label: str = Field(max_length=50)


class _DocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _DocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _OADocService(BaseService[_OADoc, _DocCreate, _DocUpdate]):
    model = _OADoc


class _OASoftDocService(BaseService[_OASoftDoc, _DocCreate, _DocUpdate]):
    model = _OASoftDoc


class _OAPlainService(BaseService[_OAPlain, _DocCreate, _DocUpdate]):
    model = _OAPlain


@pytest.fixture(autouse=True)
def _reset_predicates() -> Iterator[None]:
    """Keep the process-global object-authz registry isolated per test."""
    yield
    reset_object_authz_predicates()


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# apply_object_authz — the central decision, unit-tested in isolation
# --------------------------------------------------------------------------- #
def test_owner_is_allowed() -> None:
    owner = uuid.uuid4()
    doc = _OADoc(label="x", owner_id=owner)
    assert apply_object_authz(_OADoc, doc, owner, AuditAction.UPDATED) is True


def test_non_owner_is_denied() -> None:
    doc = _OADoc(label="x", owner_id=uuid.uuid4())
    assert apply_object_authz(_OADoc, doc, uuid.uuid4(), AuditAction.UPDATED) is False


def test_actorless_write_on_an_owned_row_is_denied() -> None:
    # An owned row with no bound actor (out-of-request) fails closed.
    doc = _OADoc(label="x", owner_id=uuid.uuid4())
    assert apply_object_authz(_OADoc, doc, None, AuditAction.DELETED) is False


def test_unowned_row_is_unrestricted() -> None:
    # owner_id is None (best-effort, like a nullable actor stamp): no owner to protect.
    doc = _OADoc(label="x")
    assert apply_object_authz(_OADoc, doc, uuid.uuid4(), AuditAction.UPDATED) is True


def test_non_owned_model_is_unrestricted() -> None:
    plain = _OAPlain(label="x")
    assert apply_object_authz(_OAPlain, plain, uuid.uuid4(), AuditAction.UPDATED) is True


def test_registered_predicate_composes_and_is_action_aware() -> None:
    def only_updates(
        model: type[SQLModel], entity: SQLModel, actor: uuid.UUID | None, action: AuditAction
    ) -> bool:
        return action is AuditAction.UPDATED

    register_object_authz_predicate(only_updates)
    register_object_authz_predicate(only_updates)  # idempotent: registered once
    assert registered_object_authz_predicates() == (only_updates,)

    plain = _OAPlain(label="x")
    actor = uuid.uuid4()
    # Built-in allows (not owned); the predicate allows UPDATE but denies DELETE.
    assert apply_object_authz(_OAPlain, plain, actor, AuditAction.UPDATED) is True
    assert apply_object_authz(_OAPlain, plain, actor, AuditAction.DELETED) is False


# --------------------------------------------------------------------------- #
# BaseService — the chokepoint stamps the owner and enforces the gate
# --------------------------------------------------------------------------- #
def test_create_stamps_the_owner(engine: Engine) -> None:
    actor = uuid.uuid4()
    with Session(engine) as session, bind_audit_actor(actor):
        doc = _OADocService().create(session, _DocCreate(label="x"))
        assert doc.owner_id == actor


def test_owner_may_update_and_hard_delete(engine: Engine) -> None:
    owner = uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc = service.create(session, _DocCreate(label="x"))
        doc_id, version = doc.id, doc.version
    with Session(engine) as session, bind_audit_actor(owner):
        updated = service.update(session, doc_id, _DocUpdate(label="y", version=version))
        assert updated.label == "y"
        service.delete(session, doc_id)  # no soft-delete mixin -> hard delete
    with Session(engine) as session:
        with pytest.raises(NotFoundError):
            service.get(session, doc_id)


def test_non_owner_cannot_update(engine: Engine) -> None:
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc = service.create(session, _DocCreate(label="x"))
        doc_id, version = doc.id, doc.version
    with Session(engine) as session, bind_audit_actor(intruder):
        with pytest.raises(PermissionDeniedError):
            service.update(session, doc_id, _DocUpdate(label="hacked", version=version))
    # The uncommitted write was discarded on session close: the row is untouched.
    with Session(engine) as session:
        assert service.get(session, doc_id).label == "x"


def test_non_owner_is_denied_before_the_concurrency_check(engine: Engine) -> None:
    # Authorization precedes the OCC check: a non-owner is refused 403 whatever version
    # they send -- a deliberately stale version still raises PermissionDeniedError, not
    # StaleDataError (ADR 0029). Were the order reversed, this would be a 409.
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc_id = service.create(session, _DocCreate(label="x")).id
    with Session(engine) as session, bind_audit_actor(intruder):
        with pytest.raises(PermissionDeniedError):
            service.update(session, doc_id, _DocUpdate(label="hacked", version=999))


def test_non_owner_cannot_hard_delete(engine: Engine) -> None:
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc = service.create(session, _DocCreate(label="x"))
        doc_id = doc.id
    with Session(engine) as session, bind_audit_actor(intruder):
        with pytest.raises(PermissionDeniedError):
            service.delete(session, doc_id)
    with Session(engine) as session:
        assert service.get(session, doc_id).id == doc_id  # still present


def test_non_owner_cannot_soft_delete_but_owner_can(engine: Engine) -> None:
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    service = _OASoftDocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc = service.create(session, _DocCreate(label="x"))
        doc_id = doc.id
    # A non-owner soft-delete (routed through the audited chokepoint) is refused.
    with Session(engine) as session, bind_audit_actor(intruder):
        with pytest.raises(PermissionDeniedError):
            service.delete(session, doc_id)
    # The owner may soft-delete it, and it then vanishes from reads.
    with Session(engine) as session, bind_audit_actor(owner):
        assert service.get(session, doc_id).id == doc_id
        service.delete(session, doc_id)
    with Session(engine) as session:
        with pytest.raises(NotFoundError):
            service.get(session, doc_id)


def test_reads_are_not_owner_gated(engine: Engine) -> None:
    # Object-authz is the *write* gate; read visibility is the scope-registry seam
    # (ADR 0017). A non-owner can still read an owned row through get/list.
    owner, reader = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session, bind_audit_actor(owner):
        doc = service.create(session, _DocCreate(label="x"))
        doc_id = doc.id
    with Session(engine) as session, bind_audit_actor(reader):
        assert service.get(session, doc_id).id == doc_id
        rows, total = service.list(session, skip=0, limit=10)
        assert total == 1 and rows[0].id == doc_id


def test_registered_predicate_gates_writes_through_the_chokepoint(engine: Engine) -> None:
    denied = {"locked": False}

    def deny_when_locked(
        model: type[SQLModel], entity: SQLModel, actor: uuid.UUID | None, action: AuditAction
    ) -> bool:
        return not denied["locked"]

    register_object_authz_predicate(deny_when_locked)
    service = _OAPlainService()
    with Session(engine) as session, bind_audit_actor(uuid.uuid4()):
        # create is not object-authz gated (a CREATED row has no prior owner) -> allowed.
        plain = service.create(session, _DocCreate(label="x"))
        plain_id, version = plain.id, plain.version

    denied["locked"] = True
    with Session(engine) as session, bind_audit_actor(uuid.uuid4()):
        with pytest.raises(PermissionDeniedError):
            service.update(session, plain_id, _DocUpdate(label="y", version=version))
