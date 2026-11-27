"""The optional pytest report follows ORM writes until a successful outer commit."""

from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, Column, event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, create_engine, select

from terp.core import AuditAction, BaseSchema, BaseService, BaseTable, BaseUpdateSchema, testing
from terp.core._commit_validation import UnvalidatedWriteError
from terp.core._internal.session_guard import enter_write_unit, record_write
from terp.core._orm_values import _snapshot
from terp.core._write_report import WriteReport
from terp.core.db import WriteGuardedSession


class ReportLine(BaseTable, table=True):
    __tablename__ = "test_write_report_line"
    amount: int = Field(unique=True)


class LineCreate(BaseSchema):
    amount: int


class LineEdit(BaseUpdateSchema):
    amount: int | None = None


class LineService(BaseService[ReportLine, LineCreate, LineEdit]):
    model = ReportLine

    def double(self, session, row):
        row.amount *= 2
        return self._save(session, row, AuditAction.UPDATED)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    try:
        ReportLine.__table__.create(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("session_type", [Session, WriteGuardedSession])
def test_custom_service_and_hard_delete_report_clean_commits(engine, session_type):
    with closing(WriteReport()) as report, session_type(engine) as session:
        service = LineService()
        row = service.create(session, LineCreate(amount=12))
        service.double(session, row)
        assert row.amount == 24
        service.delete(session, row.id)
        assert report.pending == [[], [], []]


def test_empty_commits_and_service_saves_without_a_changed_column_do_not_count(engine):
    with closing(WriteReport()) as report, Session(engine) as session:
        service = LineService()
        row = service.create(session, LineCreate(amount=10))
        service.update(session, row.id, LineEdit(version=row.version, amount=10))
        session.commit()
        assert report.pending == [[]]

        # A persisted framework-managed timestamp still counts as a write.
        row.updated_at += timedelta(seconds=1)
        session.commit()
        assert report.pending == [[], []]


def test_report_names_columns_after_autoflush_and_drops_failed_commits(engine):
    with closing(WriteReport()) as report, Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        row.amount = 21
        assert session.exec(select(ReportLine.amount)).one() == 21
        session.commit()
        expected = f"{ReportLine.__module__}.ReportLine [amount]"
        assert report.pending == [[], [expected]]

        session.add(ReportLine(amount=21))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert report.pending == [[], [expected]]


def test_assignment_to_an_expired_column_is_reported_when_its_old_value_is_unknown(engine):
    with closing(WriteReport()) as report, Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        session.expire(row, ["amount"])
        row.amount = 10
        session.commit()
        assert report.pending == [[], [f"{ReportLine.__module__}.ReportLine [amount]"]]


def test_savepoints_and_reverted_changes_match_the_outer_commit(engine):
    with closing(WriteReport()) as report, Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        with session.begin_nested():
            row.amount = 20
        savepoint = session.begin_nested()
        row.amount = 30
        session.flush()
        savepoint.rollback()
        row.amount = 10
        session.commit()
        assert report.pending == [[], []]

        with session.begin_nested():
            row.amount = 35
        session.rollback()
        assert report.pending == [[], []]


def test_report_distinguishes_direct_insert_and_delete_and_rollbacks(engine):
    with closing(WriteReport()) as report, Session(engine) as session:
        row = ReportLine(amount=321)
        session.add(row)
        session.commit()
        session.delete(row)
        session.commit()
        label = f"{ReportLine.__module__}.ReportLine"
        assert report.pending == [[f"{label} [<insert>, amount]"], [f"{label} [<delete>]"]]

        transient = ReportLine(amount=33)
        session.add(transient)
        session.flush()
        session.delete(transient)
        session.commit()
        assert report.pending[-1] == []


def test_observer_cleanup_with_an_open_session_and_dependency_only_flush(engine):
    # A dependency-only entry participates in ORM ordering without writing the row.
    with Session(engine) as session:
        with closing(WriteReport()) as report:
            report._accepted(object(), object(), "save")
            report._accepted(session, object(), "save")
            report._accepted(session, ReportLine(amount=10), "save")
            session.begin()
            report._flushed(session, SimpleNamespace(states={object(): (False, True)}))
            assert not any(report.journals.values())
        assert not report.journals
        session.rollback()


def test_snapshots_keep_the_original_json_and_binary_values():
    payload = {"pieces": [1, 2]}
    saved = _snapshot(payload)
    payload["pieces"].append(3)
    assert saved == {"pieces": [1, 2]}
    buffer = bytearray(b"abc")
    saved = _snapshot(memoryview(buffer))
    buffer[0] = 0
    assert saved == b"abc"


def test_summary_receives_each_commit_once_and_only_prints_names(pytestconfig, engine):
    class Reporter:
        def __init__(self):
            self.lines = []

        def write_line(self, line):
            self.lines.append(line)

        def write_sep(self, sep, heading):
            self.lines.append(heading)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pytestconfig.option, "terp_report_writes", True)
        registered, cleanups = [], []
        patch.setattr(pytestconfig.pluginmanager, "register", registered.append)
        patch.setattr(pytestconfig, "add_cleanup", cleanups.append)
        testing.pytest_configure(pytestconfig)
        report, = registered
        try:
            with Session(engine) as session:
                session.add(ReportLine(amount=321))
                session.commit()
            result = SimpleNamespace(nodeid="case.py::test_line", user_properties=[("other", 1)])
            hook = report.pytest_runtest_makereport()
            next(hook)
            with pytest.raises(StopIteration):
                hook.send(result)
            report.pytest_runtest_logreport(result)
            terminal = Reporter()
            report.pytest_terminal_summary(terminal)
            assert terminal.lines == [
                "terp write report",
                "1 ORM write transaction(s) committed, 1 with changes outside an accepted write.",
                "Findings that include application models",
                f"  case.py::test_line (1): {ReportLine.__module__}.ReportLine [<insert>, amount]",
            ]
            assert report.pending == []
        finally:
            cleanups[0]()


def test_run_wide_validation_and_fixture_share_the_same_listener(
    engine, monkeypatch, pytestconfig, request,
):
    cleanups = []
    monkeypatch.setattr(pytestconfig.option, "terp_validate_writes", True)
    monkeypatch.setattr(pytestconfig, "add_cleanup", cleanups.append)
    testing.pytest_configure(pytestconfig)
    request.getfixturevalue("terp_validate_writes")
    with Session(engine) as session:
        try:
            session.add(ReportLine(amount=10))
            with pytest.raises(UnvalidatedWriteError, match="<insert>"):
                session.commit()
        finally:
            cleanups.pop()()
        session.rollback()


def test_a_later_commit_listener_is_checked_at_the_final_flush(engine, terp_validate_writes):
    with Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))

        @event.listens_for(session, "before_commit", once=True)
        def round_again(session):
            row.amount += 1

        with pytest.raises(UnvalidatedWriteError, match="ReportLine .*amount"):
            session.commit()
        session.rollback()
        assert row.amount == 10


def test_service_state_matters_when_a_hook_restores_the_original_value(engine, terp_validate_writes):
    class RoundAgain(LineService):
        def _after_write(self, session, entity, action):
            entity.amount = 10

    with Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        with pytest.raises(UnvalidatedWriteError, match="ReportLine .*amount"):
            RoundAgain().update(session, row.id, LineEdit(version=row.version, amount=11))
        assert row.amount == 10 and row.version == 1


def test_an_append_cannot_account_for_a_change_to_an_existing_row(engine, terp_validate_writes):
    with Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        row.amount += 1
        record_write(session, row, "append")
        with pytest.raises(UnvalidatedWriteError, match="ReportLine .*amount"):
            session.commit()
        session.rollback()
        row.amount += 1
        record_write(session, row, "fields", "amount")
        session.commit()
        assert row.amount == 11


def test_a_second_service_save_advances_the_accepted_value(engine, terp_validate_writes):
    service = LineService()
    with Session(engine) as session, enter_write_unit():
        row = service.create(session, LineCreate(amount=10))
        service.double(session, row)
        # This savepoint accepts another value, then its caller abandons it.
        point = session.begin_nested()
        service.double(session, row)
        point.rollback()
        session.commit()
    with Session(engine) as reader:
        assert reader.exec(select(ReportLine.amount)).one() == 20


@pytest.mark.parametrize("flush_first", [False, True])
def test_an_accepted_insert_must_survive_the_unit(engine, terp_validate_writes, flush_first):
    with Session(engine) as session:
        row = ReportLine(amount=10)
        session.add(row)
        record_write(session, row, "append")
        if flush_first:
            session.flush()
            session.delete(row)
        else:
            session.expunge(row)
        with pytest.raises(UnvalidatedWriteError, match="<delete>" if flush_first else "<insert>"):
            session.commit()
        session.rollback()
        assert session.exec(select(ReportLine)).all() == []


def test_an_accepted_delete_must_reach_the_database(engine, terp_validate_writes):
    with Session(engine) as session:
        row = LineService().create(session, LineCreate(amount=10))
        session.delete(row)
        record_write(session, row, "remove")
        session.add(row)
        with pytest.raises(UnvalidatedWriteError, match="<delete>"):
            session.commit()
        session.rollback()
        assert session.exec(select(ReportLine.amount)).one() == 10


def test_a_later_update_accounts_only_for_its_own_operation(engine, terp_validate_writes):
    with Session(engine) as session, enter_write_unit():
        row = ReportLine(amount=10)
        session.add(row)
        session.flush()
        LineService().double(session, row)
        with pytest.raises(UnvalidatedWriteError, match="<insert>"):
            session.commit()
        session.rollback()
    with Session(engine) as reader:
        assert reader.exec(select(ReportLine)).all() == []


class ReportPayload(BaseTable, table=True):
    __tablename__ = "test_write_report_payload"
    data: dict = Field(sa_column=Column(JSON, nullable=False))


class PayloadCreate(BaseSchema):
    data: dict


class PayloadEdit(BaseUpdateSchema):
    data: dict


class PayloadService(BaseService[ReportPayload, PayloadCreate, PayloadEdit]):
    model = ReportPayload


def test_the_saved_json_distinguishes_numbers_from_booleans(engine, terp_validate_writes):
    class ChangeLabel(PayloadService):
        def _after_write(self, session, entity, action):
            entity.data = {"labels": [True]}

    ReportPayload.__table__.create(engine)
    with Session(engine) as session:
        with pytest.raises(UnvalidatedWriteError, match="ReportPayload .*data"):
            ChangeLabel().create(session, PayloadCreate(data={"labels": [1]}))
        assert session.exec(select(ReportPayload)).all() == []

        service = PayloadService()
        row = service.create(session, PayloadCreate(data={"labels": [1]}))
        row = service.update(session, row.id, PayloadEdit(version=row.version, data={"labels": [True]}))
        assert row.data["labels"][0] is True
