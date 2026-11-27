"""The optional pytest report follows ORM writes until a successful outer commit."""

from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, create_engine, select

from terp.core import AuditAction, BaseSchema, BaseService, BaseTable, BaseUpdateSchema, testing
from terp.core._write_report import WriteReport, _snapshot
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
            report._service_write(object(), object(), "save")
            report._service_write(session, object(), "save")
            report._service_write(session, ReportLine(amount=10), "save")
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
                "1 ORM write transaction(s) committed, 1 with changes outside a service save.",
                "Findings that include application models",
                f"  case.py::test_line (1): {ReportLine.__module__}.ReportLine [<insert>, amount]",
            ]
            assert report.pending == []
        finally:
            cleanups[0]()
