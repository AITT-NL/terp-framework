"""Row-scope predicate registry + business_filters: row scope is non-droppable (ADR 0017).

``BaseService.base_query`` composes soft-delete + every registered capability predicate
+ the service's ``business_filters()``; a service adds read conditions through
``business_filters`` (which can only narrow), never by overriding ``base_query``. The
registry is the seam a capability (e.g. tenancy) uses to plug in its row predicate.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from sqlalchemy import ColumnElement
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlmodel.sql.expression import SelectOfScalar

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    SoftDeleteMixin,
)
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.scoping import (
    register_scope_predicate,
    registered_scope_predicates,
    reset_scope_predicates,
)


class _ScopedMixin(SQLModel):
    """Marker a synthetic scope predicate keys off (mirrors ``TenantScopedMixin``)."""


class _Doc(BaseTable, SoftDeleteMixin, _ScopedMixin, table=True):
    __tablename__ = "scope_registry_doc"

    name: str = Field(max_length=50)
    kind: str = Field(max_length=20, default="note")


class _DocCreate(BaseSchema):
    name: str
    kind: str = "note"


class _DocUpdate(BaseUpdateSchema):
    name: str | None = None


class _DocService(BaseService[_Doc, _DocCreate, _DocUpdate]):
    model = _Doc


class _NotesOnlyService(BaseService[_Doc, _DocCreate, _DocUpdate]):
    """Adds a static read filter via the hook — no ``super()``, cannot drop scope."""

    model = _Doc

    def business_filters(self) -> Sequence[ColumnElement[bool]]:
        return (_Doc.kind == "note",)


def _notes_scope_predicate(
    model: type[SQLModel], query: SelectOfScalar
) -> SelectOfScalar:
    if issubclass(model, _ScopedMixin):
        return query.where(model.kind == "note")  # type: ignore[attr-defined]
    return query


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Snapshot the global registry, clear it, then restore — no cross-test pollution."""
    saved = registered_scope_predicates()
    reset_scope_predicates()
    try:
        yield
    finally:
        reset_scope_predicates()
        for predicate in saved:
            register_scope_predicate(predicate)


def test_register_scope_predicate_is_idempotent(isolated_registry: None) -> None:
    register_scope_predicate(_notes_scope_predicate)
    register_scope_predicate(_notes_scope_predicate)
    assert registered_scope_predicates() == (_notes_scope_predicate,)


def test_reset_scope_predicates_clears(isolated_registry: None) -> None:
    register_scope_predicate(_notes_scope_predicate)
    assert registered_scope_predicates() != ()
    reset_scope_predicates()
    assert registered_scope_predicates() == ()


def test_base_query_applies_every_registered_predicate(
    session: Session, isolated_registry: None
) -> None:
    register_scope_predicate(_notes_scope_predicate)
    service = _DocService()
    service.create(session, _DocCreate(name="a", kind="note"))
    service.create(session, _DocCreate(name="b", kind="task"))

    rows, total = service.list(session, skip=0, limit=100)
    assert total == 1
    assert {row.name for row in rows} == {"a"}


def test_business_filters_compose_on_top_of_non_droppable_scope(
    session: Session, isolated_registry: None
) -> None:
    # No registered predicates (isolated): soft-delete + business_filters still apply,
    # and business_filters cannot drop the soft-delete scope.
    service = _NotesOnlyService()
    a = service.create(session, _DocCreate(name="a", kind="note"))
    service.create(session, _DocCreate(name="b", kind="task"))

    rows, _ = service.list(session, skip=0, limit=100)
    assert {row.name for row in rows} == {"a"}  # business_filters: kind == note

    service.delete(session, a.id)  # soft-delete (_Doc is a SoftDeleteMixin)
    rows, total = service.list(session, skip=0, limit=100)
    assert (rows, total) == ([], 0)  # 'a' soft-deleted, 'b' filtered out — scope intact


def test_request_session_rescopes_a_raw_select(isolated_registry: None) -> None:
    """A raw ``select(model)`` via the request session is re-scoped (F1 backstop, ADR 0017).

    The build-time ``reads_use_base_query`` rule flags a bespoke read that issues
    ``select(<scoped model>)`` directly; this proves the *runtime* half — the
    ``WriteGuardedSession`` re-applies the row scope to a single-entity select that
    never went through ``base_query`` — and that a bare ``Session`` is unaffected.
    """
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    service = _DocService()
    try:
        with WriteGuardedSession(engine) as guarded:
            service.create(guarded, _DocCreate(name="kept", kind="note"))
            gone = service.create(guarded, _DocCreate(name="gone", kind="note"))
            service.delete(guarded, gone.id)  # soft-delete

            # A bespoke read that bypasses base_query() entirely is still scoped:
            rows = guarded.exec(select(_Doc)).all()
            assert {row.name for row in rows} == {"kept"}

        # A bare Session (a deliberate privileged/test read) is NOT re-scoped:
        with Session(engine) as bare:
            all_rows = bare.exec(select(_Doc)).all()
            assert {row.name for row in all_rows} == {"kept", "gone"}
    finally:
        engine.dispose()
