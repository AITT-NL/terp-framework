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
)
from terp.core.scoping import (
    register_owner_read_scope,
    register_scope_predicate,
    registered_scope_predicates,
)
from terp.core._internal.registry_resets import (
    reset_object_authz_predicates,
    reset_scope_predicates,
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
    """Keep the process-global authz registries isolated per test.

    The scope registry is **restored**, never reset. Clearing it is not isolation: the
    tenancy capability registers the tenant filter into it at *import*, so a reset in a
    teardown here removes that registration for every test that runs afterwards in the
    same process — which shows up as unrelated tenancy tests reading rows they should
    not, hundreds of files away from the fixture that caused it. (Observed, exactly
    that way, while this file was being written.) Snapshotting and putting the list
    back leaves only what this file registered removed.

    The object-authz registry has no import-time registrant — the built-in owner check
    is inlined in ``apply_object_authz`` rather than registered — so clearing that one
    is genuinely empty-to-empty.
    """
    installed = registered_scope_predicates()
    yield
    reset_object_authz_predicates()
    reset_scope_predicates()
    for predicate in installed:
        register_scope_predicate(predicate)


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


# --------------------------------------------------------------------------- #
# the read half of the trait (opt-in): register_owner_read_scope
# --------------------------------------------------------------------------- #
def test_owned_reads_are_unscoped_until_the_seam_is_installed(engine: Engine) -> None:
    """The gap this closes, asserted first so the opt-in has something to be opposite of.

    ``OwnedMixin`` gates writes and says so; installing the read filter was left to the
    app, and an exercise left undone reads exactly like a control that is present. A
    surface described as owner-scoped therefore returned every row to every caller who
    cleared its role.
    """
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session:
        with bind_audit_actor(theirs):
            service.create(session, _DocCreate(label="theirs"))
        with bind_audit_actor(mine):
            service.create(session, _DocCreate(label="mine"))
            rows, _total = service.list(session, skip=0, limit=50)
    assert {row.label for row in rows} == {"mine", "theirs"}


def test_the_owner_read_scope_hides_another_actors_rows(engine: Engine) -> None:
    """Composed with the write gate this is the full property OwnedMixin describes."""
    register_owner_read_scope()
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    service = _OADocService()
    with Session(engine) as session:
        with bind_audit_actor(theirs):
            service.create(session, _DocCreate(label="theirs"))
        with bind_audit_actor(mine):
            service.create(session, _DocCreate(label="mine"))
            rows, _total = service.list(session, skip=0, limit=50)
            assert {row.label for row in rows} == {"mine"}
        # And the other actor sees the mirror image, so this is a filter rather than
        # an ordering accident.
        with bind_audit_actor(theirs):
            rows, _total = service.list(session, skip=0, limit=50)
            assert {row.label for row in rows} == {"theirs"}


def test_the_owner_read_scope_leaves_unowned_rows_visible(engine: Engine) -> None:
    """Matching the write gate, which does not restrict a row with no owner to protect.

    An unowned row is what a job, a migration or a seed writes — there is nobody it
    could be scoped to, and hiding it would make the rows a system created invisible to
    every human.
    """
    register_owner_read_scope()
    service = _OADocService()
    with Session(engine) as session:
        with bind_audit_actor(None):
            service.create(session, _DocCreate(label="system"))
        with bind_audit_actor(uuid.uuid4()):
            rows, _total = service.list(session, skip=0, limit=50)
    assert {row.label for row in rows} == {"system"}


def test_an_actorless_read_is_not_narrowed_to_nothing(engine: Engine) -> None:
    """A worker or CLI has no "self" to scope to, so it sees the unscoped set.

    Narrowing to nothing would make background work silently read an empty database —
    a failure that looks like missing data rather than like a missing actor.
    """
    register_owner_read_scope()
    service = _OADocService()
    with Session(engine) as session:
        with bind_audit_actor(uuid.uuid4()):
            service.create(session, _DocCreate(label="owned"))
        rows, _total = service.list(session, skip=0, limit=50)
    assert {row.label for row in rows} == {"owned"}


def test_the_owner_read_scope_ignores_a_model_without_the_trait(engine: Engine) -> None:
    """A predicate must be a no-op for a model it does not govern (the registry contract)."""
    register_owner_read_scope()
    service = _OAPlainService()
    with Session(engine) as session:
        with bind_audit_actor(uuid.uuid4()):
            service.create(session, _DocCreate(label="plain"))
        with bind_audit_actor(uuid.uuid4()):
            rows, _total = service.list(session, skip=0, limit=50)
    assert {row.label for row in rows} == {"plain"}


def test_installing_the_owner_read_scope_twice_registers_once() -> None:
    """Idempotent, like every other registration here — a composition root may re-run."""
    before = len(registered_scope_predicates())
    register_owner_read_scope()
    register_owner_read_scope()
    assert len(registered_scope_predicates()) == before + 1
