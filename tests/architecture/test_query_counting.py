"""Counting the statements a block actually runs, so an N+1 is assertable.

The gate makes a strong claim about what a Terp app cannot get structurally wrong and
no claim at all about what it costs to run. Nothing in the platform measured a query
count, and the absences reinforce each other: nothing on the server reports latency, so
nothing in the suite asserts a bound, so the first person to notice a list endpoint
issuing one query per row is a customer.

The failure shape is dull and specific. An endpoint loads N rows and touches a
relationship per row: the count is 1 + N, the response is fine on the twelve rows the
fixture creates, nothing in the code looks wrong, and every existing test passes. It
stays that way until the table has real data in it.

What makes it testable is that the statement count is DETERMINISTIC and small while the
wall clock is neither — so this counts statements, not seconds. The assertion survives a
slow runner, a cold cache and a shared machine, and still fails the moment a loop starts
talking to the database.
"""

from __future__ import annotations

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core.testing import QueryLog, assert_max_queries, count_queries


class _Note(SQLModel, table=True):
    __tablename__ = "query_counting_note"

    id: int | None = Field(default=None, primary_key=True)
    title: str = ""


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[_Note.__table__])
    with Session(engine) as open_session:
        for index in range(5):
            open_session.add(_Note(title=f"n{index}"))
        open_session.commit()
        yield open_session


def test_one_read_is_one_statement(session: Session) -> None:
    with count_queries(session) as queries:
        session.exec(select(_Note)).all()
    assert len(queries) == 1
    assert len(queries.selects) == 1


def test_the_n_plus_one_shape_is_visible(session: Session) -> None:
    """The whole point: the count scales with the rows, and that is what to assert on."""
    rows = session.exec(select(_Note)).all()
    with count_queries(session) as queries:
        for row in rows:
            session.exec(select(_Note).where(_Note.id == row.id)).first()
    assert len(queries) == len(rows) == 5


def test_the_assertion_fires_and_shows_the_statements(session: Session) -> None:
    """"expected at most 3, got 14" without the fourteen is a puzzle, not a finding —
    and the fourteen are almost always the same SELECT with a different id, which is
    the entire diagnosis."""
    rows = session.exec(select(_Note)).all()
    with pytest.raises(AssertionError) as raised:
        with assert_max_queries(session, 2, only="FROM query_counting_note"):
            for row in rows:
                session.exec(select(_Note).where(_Note.id == row.id)).first()
    message = str(raised.value)
    assert "got 5" in message
    assert message.count("SELECT") >= 5, "the failure must list the statements that ran"


def test_a_block_within_its_bound_passes(session: Session) -> None:
    with assert_max_queries(session, 1, only="FROM query_counting_note"):
        session.exec(select(_Note)).all()


def test_only_narrows_the_count(session: Session) -> None:
    """A block that legitimately does other work still gets a precise bound."""
    with count_queries(session) as queries:
        session.exec(select(_Note)).all()
        session.exec(select(1)).all()
    assert len(queries) == 2
    assert len(queries.matching("FROM query_counting_note")) == 1


def test_the_listener_is_removed_after_the_block(session: Session) -> None:
    """A counter left attached would keep growing someone else's log, and the next
    test's bound would depend on collection order — the class of bug the runtime
    isolation in this same module exists to prevent."""
    with count_queries(session) as queries:
        session.exec(select(_Note)).all()
    before = len(queries)
    session.exec(select(_Note)).all()
    assert len(queries) == before, "the listener outlived its block"


def test_the_listener_is_removed_even_when_the_block_raises(session: Session) -> None:
    with pytest.raises(RuntimeError):
        with count_queries(session) as queries:
            session.exec(select(_Note)).all()
            raise RuntimeError("boom")
    before = len(queries)
    session.exec(select(_Note)).all()
    assert len(queries) == before


def test_it_accepts_an_engine_as_well_as_a_session(session: Session) -> None:
    """A test that has only the engine — a fixture building one directly — should not
    have to construct a session to count."""
    engine = session.get_bind()
    with count_queries(engine) as queries:
        session.exec(select(_Note)).all()
    assert len(queries) == 1


def test_the_log_reads_as_a_report() -> None:
    empty = QueryLog()
    assert "no statements" in str(empty)
    populated = QueryLog(statements=["SELECT 1", "SELECT 2"])
    rendered = str(populated)
    assert "1. SELECT 1" in rendered and "2. SELECT 2" in rendered
