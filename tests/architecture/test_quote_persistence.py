"""Owner-confirmed quote outcomes at the request session's transaction boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, Session, create_engine, select

from terp.capabilities.access import AccessService, Grant
from terp.capabilities.audit import AuditEvent, persist_audit
from terp.capabilities.groups import Group, GroupMember
from terp.core import (
    EDITOR,
    AuditPolicy,
    ConflictError,
    PermissionDeniedError,
    Principal,
    ValidationFailedError,
)
from terp.core import db
from terp.core.db import WriteGuardedSession

from .quote_service_fixture import (
    APPROVE,
    PLACE,
    Quote,
    QuoteCreate,
    QuotePatch,
    QuoteService,
)


@pytest.fixture
def engine(terp_db_url, monkeypatch) -> Iterator[Engine]:
    # The verification session must see what a new connection can read.
    engine = create_engine(terp_db_url, poolclass=NullPool)
    tables = [model.__table__ for model in (Quote, Grant, Group, GroupMember)]
    try:
        SQLModel.metadata.create_all(engine, tables=tables)
        monkeypatch.setattr(db, "get_engine", lambda: engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def service() -> QuoteService:
    return QuoteService(Principal(uuid4(), EDITOR))


@contextmanager
def _request(engine: Engine, *, commits: int) -> Iterator[Session]:
    observed = 0

    def count_commit(connection: Connection) -> None:
        nonlocal observed
        observed += 1

    event.listen(engine, "commit", count_commit)
    try:
        with contextmanager(db.get_session)() as session:
            assert isinstance(session, WriteGuardedSession)
            yield session
        assert observed == commits
    finally:
        event.remove(engine, "commit", count_commit)


def _stored(engine: Engine) -> Quote | None:
    with Session(engine) as reader:
        return reader.exec(select(Quote)).one_or_none()


def _terms(**changes) -> QuoteCreate:
    terms = dict(
        revenue="100.00",
        material_cost="37.40",
        labour_cost="22.50",
        discount_pct="25.00",
    )
    return QuoteCreate.model_validate(terms | changes)


def _create_draft(engine: Engine, service: QuoteService) -> Quote:
    terms = _terms()
    with _request(engine, commits=1) as writer:
        quote_id = service.create(writer, terms).id
    stored = _stored(engine)
    assert stored is not None
    assert stored.id == quote_id and stored.version == 1
    assert stored.model_dump(include=set(terms.model_fields_set)) == terms.model_dump(
        exclude_unset=True
    )
    assert stored.status == "draft" and stored.margin == Decimal("40.10")
    return stored


def _edit(
    engine: Engine,
    service: QuoteService,
    before: Quote,
    *,
    expected_margin: Decimal | None = None,
    **changes,
) -> Quote:
    patch = QuotePatch(version=before.version, **changes)
    with _request(engine, commits=1) as writer:
        service.update(writer, before.id, patch)
    stored = _stored(engine)
    assert stored is not None
    expected = before.model_dump(exclude={"updated_at"}) | changes
    expected["version"] = before.version + 1
    if expected_margin is not None:
        expected["margin"] = expected_margin
    assert stored.model_dump(exclude={"updated_at"}) == expected
    return stored


def _refuse_edit(
    engine: Engine,
    service: QuoteService,
    before: Quote,
    error: type[Exception],
    **changes,
) -> None:
    patch = QuotePatch(version=before.version, **changes)
    with _request(engine, commits=0) as writer, pytest.raises(error) as caught:
        service.update(writer, before.id, patch)
    assert caught.type is error
    stored = _stored(engine)
    assert stored is not None and stored.model_dump() == before.model_dump()


def test_create_and_partial_cost_edit_persist_the_complete_quote(engine, service):
    draft = _create_draft(engine, service)
    edited = _edit(
        engine,
        service,
        draft,
        material_cost=Decimal("40.10"),
        expected_margin=Decimal("37.40"),
    )
    _refuse_edit(
        engine,
        service,
        edited,
        ValidationFailedError,
        revenue=Decimal("90.00"),
        discount_pct=Decimal("25.01"),
    )


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"discount_pct": "25.01"}, ValidationFailedError),
        ({"status": "approved"}, ConflictError),
    ],
)
def test_refused_create_commits_nothing(engine, service, changes, error):
    with _request(engine, commits=0) as writer, pytest.raises(error) as caught:
        service.create(writer, _terms(**changes))
    assert caught.type is error
    assert _stored(engine) is None


def test_historical_discount_can_be_left_alone_or_corrected(engine, service):
    # Existing data from before the ceiling, on its own connection before the request.
    with Session(engine) as seed:
        seed.add(
            Quote(**_terms(discount_pct="30.00").model_dump(), margin=Decimal("40.10"))
        )
        seed.commit()
    historical = _stored(engine)
    assert historical is not None and historical.discount_pct == Decimal("30.00")
    edited = _edit(
        engine,
        service,
        historical,
        labour_cost=Decimal("20.00"),
        expected_margin=Decimal("42.60"),
    )
    _refuse_edit(
        engine, service, edited, ValidationFailedError, discount_pct=Decimal("29.00")
    )
    _edit(engine, service, edited, discount_pct=Decimal("25.00"))


def test_audit_failure_after_flush_rolls_back_both_quote_and_audit_entry(
    engine, service, terp_audit
):
    AuditEvent.__table__.create(engine)
    terp_audit(AuditPolicy.default(), sink=persist_audit)
    draft = _create_draft(engine, service)

    class AuditUnavailable(OSError):
        pass

    def fail_after_flush(session, record, policy):
        persist_audit(session, record, policy)
        session.flush()
        raise AuditUnavailable("Audit storage unavailable")

    terp_audit(AuditPolicy.default(), sink=fail_after_flush)
    _refuse_edit(
        engine, service, draft, AuditUnavailable, material_cost=Decimal("50.00")
    )
    with Session(engine) as reader:
        entries = reader.exec(select(AuditEvent.action, AuditEvent.target_id)).all()
        assert entries == [("created", str(draft.id))]


def test_approving_reopening_and_ordering_use_their_respective_grants(engine, service):
    placer = QuoteService(Principal(uuid4(), EDITOR))
    for actor, permission in ((service.principal, APPROVE), (placer.principal, PLACE)):
        with _request(engine, commits=1) as writer:
            AccessService().grant(writer, actor.id, permission.name)
    draft = _create_draft(engine, service)
    _refuse_edit(engine, placer, draft, ConflictError, status="ordered")
    _refuse_edit(engine, placer, draft, PermissionDeniedError, status="approved")
    approved = _edit(engine, service, draft, status="approved")
    _refuse_edit(engine, placer, approved, PermissionDeniedError, status="draft")
    _refuse_edit(engine, service, approved, PermissionDeniedError, status="ordered")
    reopened = _edit(engine, service, approved, status="draft")
    approved_again = _edit(engine, service, reopened, status="approved")
    _edit(engine, placer, approved_again, status="ordered")
