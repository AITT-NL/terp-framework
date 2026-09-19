"""The one place the CLI reaches for the application's engine and opens a session.

``get_engine`` lives under ``terp.core._internal``. A module may not import it at all
(``no_internal_imports``); the CLI legitimately may, because it is the operator's tool
rather than application code and there is no public seam that hands out the engine a
command has to share with the running app. What is not legitimate is reaching for it
from seven different commands, which is what this replaces.

Seven copies of the same two lines is seven places a change has to find, and the count
is what the framework-package scan reads: every copy is a separate
``no_internal_imports`` and ``no_raw_session_construction`` finding against
``packages/backend/cli``, recorded as debt in ``packages/backend/UNSCANNED.json``.
Routing them through here makes it one of each, so the record shrinks rather than grows
as commands are added -- which is the only direction that record moves.

Imported lazily by its callers, like the imports it replaces: a CLI that paid for the
database stack on ``terp --help`` would be the wrong trade.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlmodel import Session

__all__ = ["cli_engine", "cli_session", "cli_session_factory"]


def cli_engine() -> Engine:
    """The engine the application is configured with."""
    from terp.core._internal.engine import get_engine

    return get_engine()


def cli_session_factory(engine: Engine | None = None) -> Callable[[], Session]:
    """A callable that opens a session, for a consumer that manages its own lifetime.

    The worker and the scheduler take one of these rather than a session: they open and
    close one per cycle for as long as they run, so handing them an already-open session
    would hold a connection for the life of the process.
    """
    from sqlmodel import Session

    bound = cli_engine() if engine is None else engine
    return lambda: Session(bound)


@contextlib.contextmanager
def cli_session() -> Iterator[Session]:
    """One session for the span of a single command."""
    with cli_session_factory()() as session:
        yield session
