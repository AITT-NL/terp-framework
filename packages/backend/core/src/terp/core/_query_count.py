"""Counting the statements a block of code actually runs.

Lifted out of ``terp.core.testing`` when that module crossed the 500-line cap. It is
the natural seam: everything here answers one question -- how many statements did that
block issue -- and nothing else in the plugin asks it. ``terp.core.testing`` re-exports
the three public names, so a test importing them is unaffected.
"""

from __future__ import annotations

import contextlib
import dataclasses
import re
from collections.abc import Iterator
from typing import Any

from sqlalchemy import event as sa_event

__all__ = ["QueryLog", "assert_max_queries", "count_queries"]


# --------------------------------------------------------------------------- #
# Counting the statements a block actually runs                                 #
# --------------------------------------------------------------------------- #
#
# The gate makes a strong claim about what this code cannot get structurally wrong and
# no claim at all about what it costs to run. Nothing in the platform measures a query
# count, and the absences reinforce each other: nothing on the server reports latency,
# nothing in the suite asserts a bound, so an N+1 on a list route is found by a customer
# rather than by a test.
#
# The shape of the failure is specific and dull. A list endpoint loads N rows and then
# touches a relationship per row, so the query count is 1 + N and the response time is
# fine on the twelve rows the fixture creates. Nothing about the code looks wrong,
# every existing test passes, and it stays that way until a table has real data in it.
#
# What makes it testable is that the statement count is DETERMINISTIC and small, while
# the wall clock is neither. So this counts statements, not seconds: an assertion that
# survives a slow CI runner, a cold cache and a shared machine, and still fails the
# moment a loop starts talking to the database.


@dataclasses.dataclass
class QueryLog:
    """Every SQL statement executed through the bound engine while it was open."""

    statements: list[str] = dataclasses.field(default_factory=list)

    def __len__(self) -> int:
        return len(self.statements)

    def matching(self, pattern: str) -> list[str]:
        """The statements matching *pattern*, case-insensitively.

        For narrowing an assertion to the part of the block under test -- the SELECTs
        against one table, say -- when the block legitimately does other work too.

        A regex when the string is one, and a literal substring when it is not. That
        fallback is the difference between a usable tool and a trap here, because the
        obvious pattern to write is a fragment of SQL: ``only="count(*)"`` is not a
        valid regex (``nothing to repeat``) and would raise instead of asserting, and
        ``only="a+b"`` is valid, matches nothing, and would pass the bound vacuously --
        which is worse, because it looks like it worked.
        """
        try:
            expression = re.compile(pattern, re.IGNORECASE)
        except re.error:
            expression = re.compile(re.escape(pattern), re.IGNORECASE)
        return [
            statement for statement in self.statements if expression.search(statement)
        ]

    @property
    def selects(self) -> list[str]:
        return [
            statement
            for statement in self.statements
            if statement.lstrip().upper().startswith("SELECT")
        ]

    def __str__(self) -> str:  # pragma: no cover - diagnostic formatting
        if not self.statements:
            return "(no statements)"
        return "\n".join(
            f"  {index:>3}. {' '.join(statement.split())[:160]}"
            for index, statement in enumerate(self.statements, start=1)
        )


def _engine_of(target: Any) -> Any:
    """The engine behind a Session, or *target* itself when it is already one."""
    bind = getattr(target, "get_bind", None)
    return bind() if callable(bind) else target


@contextlib.contextmanager
def count_queries(target: Any) -> Iterator[QueryLog]:
    """Record every statement the bound engine executes inside the block.

    *target* is a ``Session`` (the usual case -- the one a test already has) or an
    ``Engine``. Counts at the cursor, so it sees exactly what reached the database:
    ORM lazy loads, raw ``execute`` calls, and the implicit SELECT a flush emits are
    all statements and all counted.

    The log stays readable after the block, so a failing assertion can print what ran
    rather than only how many did::

        with count_queries(session) as queries:
            client.get("/api/v1/invoices/")
        assert len(queries.selects) <= 3, queries
    """
    engine = _engine_of(target)
    log = QueryLog()

    def _record(_conn, _cursor, statement, _params, _context, _executemany) -> None:
        log.statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", _record)
    try:
        yield log
    finally:
        sa_event.remove(engine, "before_cursor_execute", _record)


@contextlib.contextmanager
def assert_max_queries(target: Any, limit: int, *, only: str | None = None) -> Iterator[QueryLog]:
    """Fail the test if the block runs more than *limit* statements.

    *only* narrows the count to statements matching that pattern, for a block that
    legitimately does other work -- ``only="FROM invoice"`` counts the reads of one
    table and ignores the session's own bookkeeping.

    The failure prints every statement that ran, because "expected at most 3, got 14"
    without the fourteen is a puzzle rather than a finding -- and the fourteen are
    almost always the same SELECT with a different id, which is the whole diagnosis::

        with assert_max_queries(session, 3, only="FROM invoice"):
            client.get("/api/v1/invoices/")

    Pick the limit from what the endpoint SHOULD do, not from what it currently does.
    A bound recorded from the current behaviour passes forever and asserts nothing;
    the number is a claim about the shape of the query, and the point is that adding
    a row to the fixture must not change it.
    """
    with count_queries(target) as log:
        yield log
    counted = log.matching(only) if only else log.statements
    assert len(counted) <= limit, (
        f"expected at most {limit} statement(s)"
        + (f" matching {only!r}" if only else "")
        + f", got {len(counted)}:\n{log}"
    )
