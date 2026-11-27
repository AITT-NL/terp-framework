"""Owner-confirmed quote outcomes at the request session's transaction boundary."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, event
from sqlalchemy.orm.exc import StaleDataError as ORMStaleDataError
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, Session, create_engine, select

from terp.capabilities.access import AccessService, Grant
from terp.capabilities.audit import AuditEvent, persist_audit
from terp.capabilities.groups import Group, GroupMember
from terp.capabilities.outbox import (
    KIND_EVENT,
    STATUS_PENDING,
    OutboxMessage,
    outbox_event_dispatcher,
)
from terp.core import (
    EDITOR,
    AuditPolicy,
    BaseSchema,
    ConflictError,
    EventCatalog,
    InProcessJobQueue,
    JobCatalog,
    JobDefinition,
    PermissionDeniedError,
    Principal,
    StaleDataError,
    ValidationFailedError,
    enqueue,
)
from terp.core import db
from terp.core._commit_validation import UnvalidatedWriteError
from terp.core.db import WriteGuardedSession
from terp.core.jobs import configure_jobs

from .quote_service_fixture import (
    APPROVE,
    PLACE,
    REPRICED,
    Quote,
    QuoteCreate,
    QuotePatch,
    QuoteRevision,
    QuoteService,
    RepricingService,
)


@pytest.fixture
def engine(terp_validate_writes, terp_db_url, monkeypatch) -> Iterator[Engine]:
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
    historical_terms = _terms(discount_pct="30.00").model_dump()
    with engine.begin() as migration:
        migration.execute(Quote.__table__.insert().values(**historical_terms, margin=Decimal("40.10")))
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


@pytest.fixture
def draft_for_repricing(engine, service, terp_events, terp_audit):
    terp_audit(AuditPolicy.default(), sink=persist_audit)
    SQLModel.metadata.create_all(
        engine, tables=[QuoteRevision.__table__, OutboxMessage.__table__, AuditEvent.__table__]
    )
    terp_events(EventCatalog([REPRICED]), dispatcher=outbox_event_dispatcher)
    return _create_draft(engine, service)


def _reprice_state(engine):
    with Session(engine) as reader:
        quote = reader.exec(select(Quote)).one()
        revisions = reader.exec(select(QuoteRevision)).all()
        messages = reader.exec(select(OutboxMessage)).all()
        return (
            quote.model_dump(),
            [r.model_dump() for r in revisions],
            [m.model_dump() for m in messages],
        )


def _assert_reprice_committed(engine, draft):
    quote, revisions, messages = _reprice_state(engine)
    expected = draft.model_dump(exclude={"updated_at"})
    expected.update(
        material_cost=Decimal("40.10"),
        margin=Decimal("37.40"),
        version=draft.version + 1,
    )
    quote.pop("updated_at")
    assert quote == expected
    (revision,) = revisions
    assert revision["quote_id"] == draft.id and revision["margin"] == Decimal("37.40")
    (message,) = messages
    assert (message["kind"], message["status"], message["name"]) == (
        KIND_EVENT,
        STATUS_PENDING,
        REPRICED.name,
    )
    assert message["payload"]["payload"] == {
        "quote_id": str(draft.id),
        "margin": "37.40",
    }


class RepriceInterrupted(Exception):
    pass


def _interrupt_after_flush(session):
    # Read the database on the writer's connection before raising. Disabling autoflush
    # keeps these verification queries from flushing the pending work themselves.
    with session.no_autoflush:
        assert session.exec(select(Quote.margin)).one() == Decimal("37.40")
        assert session.exec(select(QuoteRevision.margin)).one() == Decimal("37.40")
        assert session.exec(select(OutboxMessage.name)).one() == REPRICED.name
    raise RepriceInterrupted


class _InterruptedRequest(RepricingService):
    def _after_write(self, session, entity, action):
        super()._after_write(session, entity, action)
        _interrupt_after_flush(session)


class _LateMarginRequest(RepricingService):
    def _after_write(self, session, entity, action):
        super()._after_write(session, entity, action)
        entity.margin += Decimal("0.01")


@contextmanager
def _check_reprice(engine, draft, outcome):
    error = {"interrupt": RepriceInterrupted, "late-edit": UnvalidatedWriteError}.get(outcome)
    expectation = pytest.raises(error) if error else nullcontext()
    with _request(engine, commits=int(error is None)) as writer, expectation as caught:
        yield writer
    if outcome == "late-edit":
        assert str(caught.value) == f"Unvalidated ORM write: {Quote.__module__}.Quote [margin]"
    if error:
        assert _reprice_state(engine) == (draft.model_dump(), [], [])
    else:
        _assert_reprice_committed(engine, draft)
    with Session(engine) as reader:
        actions = sorted(reader.exec(select(AuditEvent.action)).all())
        assert actions == (["created"] if error else ["created", "created", "updated"])


@pytest.mark.parametrize("outcome", ["commit", "interrupt", "late-edit"])
def test_request_commits_quote_revision_and_event_together(
    engine, service, draft_for_repricing, outcome
):
    draft = draft_for_repricing
    repricer = {
        "commit": RepricingService, "interrupt": _InterruptedRequest, "late-edit": _LateMarginRequest,
    }[outcome](service.principal)
    with _check_reprice(engine, draft, outcome) as writer:
        repricer.update(
            writer,
            draft.id,
            QuotePatch(version=draft.version, material_cost=Decimal("40.10")),
        )


class RepriceCommand(BaseSchema):
    quote_id: UUID
    version: int
    material_cost: Decimal


@pytest.mark.parametrize("outcome", ["commit", "interrupt", "late-edit"])
def test_job_owns_the_commit_after_the_nested_service_returns(
    engine, service, draft_for_repricing, outcome
):
    draft = draft_for_repricing

    def reprice(context, command):
        quote = RepricingService(service.principal).update(
            context.session,
            command.quote_id,
            QuotePatch(version=command.version, material_cost=command.material_cost),
        )
        if outcome == "interrupt":
            _interrupt_after_flush(context.session)
        if outcome == "late-edit":
            quote.margin += Decimal("0.01")

    job = JobDefinition(
        name="quotes.reprice", payload_schema=RepriceCommand, handler=reprice
    )
    configure_jobs(
        JobCatalog([job]),
        queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(engine)),
    )
    command = RepriceCommand(
        quote_id=draft.id, version=draft.version, material_cost=Decimal("40.10")
    )
    with _check_reprice(engine, draft, outcome) as producer:
        enqueue(producer, job=job, payload=command)


def test_competing_reprices_persist_only_the_winners_revision_and_event(
    engine, service, draft_for_repricing
):
    draft = draft_for_repricing
    repricer = RepricingService(service.principal)
    with (
        _request(engine, commits=1) as winner,
        contextmanager(db.get_session)() as loser,
    ):
        winner_quote = repricer.get(winner, draft.id)
        loser_quote = repricer.get(loser, draft.id)
        assert winner_quote.version == loser_quote.version == draft.version
        repricer.update(
            winner,
            draft.id,
            QuotePatch(version=draft.version, material_cost=Decimal("40.10")),
        )
        _assert_reprice_committed(engine, draft)
        committed = _reprice_state(engine)
        with pytest.raises(StaleDataError) as caught:
            repricer.update(
                loser,
                draft.id,
                QuotePatch(version=draft.version, material_cost=Decimal("41.00")),
            )
        # Both writers loaded the same version. The database rejected the losing update.
        assert isinstance(caught.value.__cause__, ORMStaleDataError)
    assert _reprice_state(engine) == committed


def test_savepoint_release_defers_to_outer_validation_and_rollback(engine, service):
    draft = _create_draft(engine, service)
    with Session(engine) as session:
        with session.begin_nested():
            row = session.get(Quote, draft.id)
            row.margin += Decimal("0.01")
        # The first write occurred inside the savepoint. It must still be private.
        assert _stored(engine).margin == draft.margin
        with pytest.raises(UnvalidatedWriteError, match="Quote .*margin"):
            session.commit()
        row.margin = draft.margin
        with pytest.raises(UnvalidatedWriteError):
            session.commit()
        session.rollback()
        assert _stored(engine).model_dump() == draft.model_dump()
        savepoint = session.begin_nested()
        row.margin += Decimal("0.01")
        session.flush()
        savepoint.rollback()
        session.commit()
        service.update(session, draft.id, QuotePatch(version=draft.version, labour_cost=Decimal("20")))
    assert _stored(engine).margin == Decimal("42.60")
