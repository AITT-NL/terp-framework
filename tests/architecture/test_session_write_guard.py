"""Runtime write-guard: the request ``Session`` refuses writes outside the chokepoint.

The structural counterpart to the build-time ``mutations_emit_audit`` rule (ADR
0015): :class:`~terp.core._internal.session_guard.WriteGuardedSession` — handed out
by :data:`terp.core.db.SessionDep` — raises
:class:`~terp.core._internal.session_guard.UnauditedWriteError` on any persistence
(``add`` / ``delete`` / ``merge`` / ``commit`` / a ``bulk_*`` helper / a DML
``execute`` / ``exec``) attempted outside the ``BaseService`` write scope, *whatever*
the session variable is named. Reads pass through, and ``BaseService.create`` /
``update`` / ``delete`` work because the chokepoint opens the scope for them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, SQLModel, create_engine, select

from terp.core import (
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ConflictError,
    SoftDeleteMixin,
)
from terp.core._internal.session_guard import (
    ReadOnlyRequestError,
    UnauditedWriteError,
    WriteGuardedSession,
    allow_session_writes,
    read_only_request,
)
from terp.core.db import get_session


class _GuardWidget(BaseTable, table=True):
    __tablename__ = "test_guard_widget"

    name: str = Field(max_length=50)


class _GuardWidgetCreate(BaseSchema):
    name: str = Field(max_length=50)


class _GuardWidgetUpdate(BaseUpdateSchema):
    name: str | None = None


class _GuardWidgetService(BaseService[_GuardWidget, _GuardWidgetCreate, _GuardWidgetUpdate]):
    model = _GuardWidget


class _ScopedWidget(BaseTable, SoftDeleteMixin, table=True):
    """A soft-delete (scope-trait) model: a hidden row must not return by id."""

    __tablename__ = "test_scoped_widget"

    name: str = Field(max_length=50)


class _ScopedWidgetCreate(BaseSchema):
    name: str = Field(max_length=50)


class _ScopedWidgetUpdate(BaseUpdateSchema):
    name: str | None = None


class _ScopedWidgetService(
    BaseService[_ScopedWidget, _ScopedWidgetCreate, _ScopedWidgetUpdate]
):
    model = _ScopedWidget


@pytest.fixture
def guarded_session() -> Iterator[WriteGuardedSession]:
    """A write-guarded session over a throwaway in-memory database."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with WriteGuardedSession(engine) as session:
        yield session
    engine.dispose()


def test_get_session_yields_write_guarded_session() -> None:
    """``SessionDep`` hands out the guarded session, not a bare ``Session``."""
    generator = get_session()
    session = next(generator)
    try:
        assert isinstance(session, WriteGuardedSession)
    finally:
        generator.close()


def test_reads_are_allowed_outside_the_write_scope(
    guarded_session: WriteGuardedSession,
) -> None:
    """A ``SELECT`` through ``exec`` / ``execute`` never needs the write scope."""
    assert guarded_session.exec(select(_GuardWidget)).all() == []
    assert list(guarded_session.execute(select(_GuardWidget)).all()) == []


def _seed_scoped(session: WriteGuardedSession) -> tuple[_ScopedWidget, _ScopedWidget]:
    """Create a live row and a soft-deleted row, returning ``(live, hidden)``."""
    service = _ScopedWidgetService()
    live = service.create(session, _ScopedWidgetCreate(name="live"))
    hidden = service.create(session, _ScopedWidgetCreate(name="hidden"))
    service.delete(session, hidden.id)  # soft-delete: stamps deleted_at
    return live, hidden


def test_get_re_scopes_a_soft_deleted_row(
    guarded_session: WriteGuardedSession,
) -> None:
    """``session.get(ScopedModel, id)`` hides a soft-deleted row (the F1 read backstop).

    A primary-key load bypasses ``base_query``, so without the guard's scoped ``get``
    it would resurrect a soft-deleted (or cross-tenant) row by id. The live row is
    still returned.
    """
    live, hidden = _seed_scoped(guarded_session)
    assert guarded_session.get(_ScopedWidget, hidden.id) is None
    fetched = guarded_session.get(_ScopedWidget, live.id)
    assert fetched is not None and fetched.id == live.id


def test_get_on_unscoped_model_uses_the_fast_path(
    guarded_session: WriteGuardedSession,
) -> None:
    """A model with no row scope keeps the parent ``get`` (identity-map) behavior."""
    created = _GuardWidgetService().create(guarded_session, _GuardWidgetCreate(name="u"))
    fetched = guarded_session.get(_GuardWidget, created.id)
    assert fetched is not None and fetched.id == created.id
    # A non-class first argument falls straight through to the parent (and errors there).
    with pytest.raises(Exception):  # noqa: B017 - parent get() rejects a non-entity
        guarded_session.get("not-a-model", created.id)


def test_get_with_options_preserves_them_and_keeps_scope(
    guarded_session: WriteGuardedSession,
) -> None:
    """``get()`` with options (e.g. ``populate_existing``) honors them AND stays scoped.

    The scoped fast path rebuilds the lookup as a select, so it cannot carry ``get()``'s
    keyword options; when any are passed the guard confirms scope visibility with a
    primary-key probe and delegates to the parent ``get()`` so the option (a lock via
    ``with_for_update``, loader options, a forced refresh) is honored — while a
    soft-deleted / cross-tenant row is still filtered out, even when it is resident in
    the identity map from the soft-delete.
    """
    live, hidden = _seed_scoped(guarded_session)
    fetched = guarded_session.get(_ScopedWidget, live.id, populate_existing=True)
    assert fetched is not None and fetched.id == live.id
    assert guarded_session.get(_ScopedWidget, hidden.id, populate_existing=True) is None


def test_scalars_and_scalar_re_scope_a_soft_deleted_row(
    guarded_session: WriteGuardedSession,
) -> None:
    """``session.scalars`` / ``scalar`` re-scope a single-entity ``select(model)`` like ``exec``."""
    live, hidden = _seed_scoped(guarded_session)
    names = {row.name for row in guarded_session.scalars(select(_ScopedWidget)).all()}
    assert names == {"live"}
    assert (
        guarded_session.scalar(select(_ScopedWidget).where(_ScopedWidget.id == hidden.id))
        is None
    )
    assert (
        guarded_session.scalar(
            select(_ScopedWidget).where(_ScopedWidget.id == live.id)
        ).id
        == live.id
    )


def test_scalars_and_scalar_dml_fail_closed_outside_scope(
    guarded_session: WriteGuardedSession,
) -> None:
    """A DML statement through ``scalars`` / ``scalar`` still needs the write scope."""
    with pytest.raises(UnauditedWriteError):
        guarded_session.scalars(update(_GuardWidget).values(name="x"))
    with pytest.raises(UnauditedWriteError):
        guarded_session.scalar(update(_GuardWidget).values(name="x"))


def test_write_during_read_only_request_fails_closed(
    guarded_session: WriteGuardedSession,
) -> None:
    """A ``BaseService`` write inside a read-only (safe-method) request is refused.

    The deny-by-default guard authorizes a safe HTTP method at the *read* tier, so the
    chokepoint must refuse a mutation while such a request is in flight — even though
    the write itself opens ``allow_session_writes`` — so a read-tier caller cannot
    perform a write (the F2 privilege-tier escape).
    """
    service = _GuardWidgetService()
    with read_only_request(True):
        with pytest.raises(ReadOnlyRequestError):
            service.create(guarded_session, _GuardWidgetCreate(name="x"))
        # Reads still work while read-only.
        assert guarded_session.exec(select(_GuardWidget)).all() == []
    # Outside the read-only scope the same write succeeds.
    created = service.create(guarded_session, _GuardWidgetCreate(name="y"))
    assert created.name == "y"


_BLOCKED_WRITES: list[tuple[str, Callable[[WriteGuardedSession], object]]] = [
    ("add", lambda s: s.add(_GuardWidget(name="x"))),
    ("add_all", lambda s: s.add_all([_GuardWidget(name="x")])),
    ("delete", lambda s: s.delete(_GuardWidget(name="x"))),
    ("merge", lambda s: s.merge(_GuardWidget(name="x"))),
    ("commit", lambda s: s.commit()),
    ("connection", lambda s: s.connection()),
    ("bulk_save_objects", lambda s: s.bulk_save_objects([_GuardWidget(name="x")])),
    ("bulk_insert_mappings", lambda s: s.bulk_insert_mappings(inspect(_GuardWidget), [])),
    ("bulk_update_mappings", lambda s: s.bulk_update_mappings(inspect(_GuardWidget), [])),
    ("exec_dml", lambda s: s.exec(update(_GuardWidget).values(name="x"))),
    ("execute_text", lambda s: s.execute(text("UPDATE test_guard_widget SET name='x'"))),
    ("execute_dml", lambda s: s.execute(update(_GuardWidget).values(name="x"))),
]


@pytest.mark.parametrize(
    "operation",
    [operation for _, operation in _BLOCKED_WRITES],
    ids=[name for name, _ in _BLOCKED_WRITES],
)
def test_write_outside_scope_fails_closed(
    guarded_session: WriteGuardedSession,
    operation: Callable[[WriteGuardedSession], object],
) -> None:
    """Every persistence verb raises ``UnauditedWriteError`` outside the chokepoint."""
    with pytest.raises(UnauditedWriteError):
        operation(guarded_session)


def test_writes_inside_scope_are_permitted(
    guarded_session: WriteGuardedSession,
) -> None:
    """Inside ``allow_session_writes`` every verb runs through to the real session."""
    mapper = inspect(_GuardWidget)
    with allow_session_writes():
        guarded_session.add_all([_GuardWidget(name="a")])
        guarded_session.merge(_GuardWidget(name="b"))
        assert guarded_session.connection() is not None
        guarded_session.commit()
        guarded_session.bulk_save_objects([_GuardWidget(name="c")])
        guarded_session.bulk_insert_mappings(mapper, [])
        guarded_session.bulk_update_mappings(mapper, [])
        guarded_session.execute(update(_GuardWidget).values(name="z"))
        guarded_session.commit()
    names = {row.name for row in guarded_session.exec(select(_GuardWidget)).all()}
    assert names == {"z"}


def test_base_service_persists_through_guarded_session(
    guarded_session: WriteGuardedSession,
) -> None:
    """The chokepoint opens the scope, so CRUD works — but a raw write still fails."""
    service = _GuardWidgetService()

    created = service.create(guarded_session, _GuardWidgetCreate(name="alpha"))
    assert created.name == "alpha"

    updated = service.update(
        guarded_session,
        created.id,
        _GuardWidgetUpdate(name="beta", version=created.version),
    )
    assert updated.name == "beta"

    service.delete(guarded_session, created.id)
    assert service.list(guarded_session, skip=0, limit=10) == ([], 0)

    # The same session refuses a write that bypasses BaseService.
    with pytest.raises(UnauditedWriteError):
        guarded_session.add(_GuardWidget(name="gamma"))


class _RawAfterWriteService(
    BaseService[_GuardWidget, _GuardWidgetCreate, _GuardWidgetUpdate]
):
    """``_after_write`` smuggles a RAW session write — must fail closed (F5)."""

    model = _GuardWidget

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        session.add(_GuardWidget(name="smuggled"))  # type: ignore[attr-defined]


class _NestedAfterWriteService(
    BaseService[_GuardWidget, _GuardWidgetCreate, _GuardWidgetUpdate]
):
    """``_after_write`` persists a derived row through the audited chokepoint — allowed."""

    model = _GuardWidget

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        if action is AuditAction.CREATED and entity.name == "trigger":  # type: ignore[attr-defined]
            _GuardWidgetService()._save(
                session,  # type: ignore[arg-type]
                _GuardWidget(name="derived"),
                AuditAction.CREATED,
            )


def test_after_write_raw_write_fails_closed(
    guarded_session: WriteGuardedSession,
) -> None:
    """A raw session write inside ``_after_write`` is refused — the F5 seam is closed.

    ``_after_write`` runs inside the write, but ``BaseService`` re-closes the scope
    around it (``forbid_session_writes``), so a bare ``session.add`` there no longer
    rides the commit unaudited.
    """
    with pytest.raises(UnauditedWriteError):
        _RawAfterWriteService().create(guarded_session, _GuardWidgetCreate(name="x"))


def test_after_write_may_write_through_the_chokepoint(
    guarded_session: WriteGuardedSession,
) -> None:
    """``_after_write`` can still persist a derived row via ``self._save`` (it re-opens the scope)."""
    _NestedAfterWriteService().create(guarded_session, _GuardWidgetCreate(name="trigger"))
    names = {row.name for row in guarded_session.exec(select(_GuardWidget)).all()}
    assert names == {"trigger", "derived"}


# --------------------------------------------------------------------------- #
# commit-ownership: the chokepoint owns a single, re-entrant commit (ADR 0038)
# --------------------------------------------------------------------------- #
class _CountingSession:
    """A session double that counts commits / flushes / refreshes (no real DB)."""

    def __init__(self, *, commit_error: bool = False, flush_error: bool = False) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.flushes = 0
        self.refreshes = 0
        self.rollbacks = 0
        self.commit_error = commit_error
        self.flush_error = flush_error

    def add(self, entity: object) -> None:
        self.added.append(entity)

    def delete(self, entity: object) -> None:
        self.deleted.append(entity)

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error:
            raise IntegrityError("INSERT", {}, Exception("duplicate row"))

    def flush(self) -> None:
        self.flushes += 1
        if self.flush_error:
            raise IntegrityError("INSERT", {}, Exception("duplicate nested row"))

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, entity: object) -> None:
        self.refreshes += 1


class _NestedSaveService(BaseService):  # type: ignore[type-arg]
    """Its ``_after_write`` re-enters via ``self._save`` to persist a derived row."""

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        if action is AuditAction.CREATED and getattr(entity, "name", "") == "trigger":
            BaseService()._save(  # type: ignore[arg-type]
                session, SimpleNamespace(id=uuid.uuid4(), name="derived"), AuditAction.CREATED
            )


class _NestedRemoveService(BaseService):  # type: ignore[type-arg]
    """Its ``_after_write`` re-enters via ``self._remove`` to delete a derived row."""

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        if action is AuditAction.CREATED and getattr(entity, "name", "") == "trigger":
            BaseService()._remove(session, SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]


class _FailingAfterWriteService(BaseService):  # type: ignore[type-arg]
    """Its ``_after_write`` fails after the row + audit are staged."""

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        raise RuntimeError("side effect failed")


def test_nested_save_commits_once_at_the_outermost_write() -> None:
    """A nested ``_save`` joins the unit: one commit, the inner write only flushes (ADR 0038)."""
    session = _CountingSession()
    trigger = SimpleNamespace(id=uuid.uuid4(), name="trigger")
    _NestedSaveService()._save(session, trigger, AuditAction.CREATED)  # type: ignore[arg-type]
    # Both rows are staged, the inner write flushed, and the outermost commit fired once.
    assert len(session.added) == 2
    assert session.commits == 1
    assert session.flushes == 1
    assert session.refreshes == 1


def test_outer_save_commit_conflict_rolls_back_and_maps_to_conflict() -> None:
    """An outermost commit IntegrityError keeps the existing uniform 409 behavior."""
    session = _CountingSession(commit_error=True)
    entity = SimpleNamespace(id=uuid.uuid4(), name="x")
    with pytest.raises(ConflictError):
        BaseService()._save(session, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert session.commits == 1
    assert session.rollbacks == 1


def test_nested_save_flush_conflict_rolls_back_and_maps_to_conflict() -> None:
    """A nested flush IntegrityError is still the uniform 409 path, with rollback."""
    session = _CountingSession(flush_error=True)
    trigger = SimpleNamespace(id=uuid.uuid4(), name="trigger")
    with pytest.raises(ConflictError):
        _NestedSaveService()._save(session, trigger, AuditAction.CREATED)  # type: ignore[arg-type]
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.flushes == 1


def test_outer_after_write_failure_rolls_back_the_unit() -> None:
    """A failing hook aborts the outermost unit and rolls back before propagating."""
    session = _CountingSession()
    entity = SimpleNamespace(id=uuid.uuid4(), name="x")
    with pytest.raises(RuntimeError, match="side effect failed"):
        _FailingAfterWriteService()._save(session, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert session.commits == 0
    assert session.rollbacks == 1


def test_nested_remove_commits_once_at_the_outermost_write() -> None:
    """A nested ``_remove`` joins the unit too: one commit, the inner delete only flushes."""
    session = _CountingSession()
    trigger = SimpleNamespace(id=uuid.uuid4(), name="trigger")
    _NestedRemoveService()._save(session, trigger, AuditAction.CREATED)  # type: ignore[arg-type]
    assert len(session.deleted) == 1
    assert session.commits == 1
    assert session.flushes == 1


def test_nested_remove_flush_conflict_rolls_back_and_maps_to_conflict() -> None:
    """A nested ``_remove`` flush IntegrityError is also the uniform 409 path."""
    session = _CountingSession(flush_error=True)
    trigger = SimpleNamespace(id=uuid.uuid4(), name="trigger")
    with pytest.raises(ConflictError):
        _NestedRemoveService()._save(session, trigger, AuditAction.CREATED)  # type: ignore[arg-type]
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.flushes == 1


def test_outer_remove_after_write_failure_rolls_back_the_unit() -> None:
    """A failing delete hook aborts the outermost unit and rolls back before propagating."""
    session = _CountingSession()
    entity = SimpleNamespace(id=uuid.uuid4(), name="x")
    with pytest.raises(RuntimeError, match="side effect failed"):
        _FailingAfterWriteService()._remove(session, entity)  # type: ignore[arg-type]
    assert session.commits == 0
    assert session.rollbacks == 1

