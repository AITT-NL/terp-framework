"""The database session seam — the only sanctioned source of a ``Session``.

Modules depend on :data:`SessionDep`; they never construct ``Session(engine)``
or touch the engine directly (engine construction lives in
:mod:`terp.core._internal.engine`, which modules must not import). This keeps
session lifecycle and transaction semantics uniform and overridable in tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from terp.core._internal.engine import get_engine
from terp.core._internal.session_guard import WriteGuardedSession


def get_session() -> Iterator[Session]:
    """Yield a request-scoped, write-guarded :class:`~sqlmodel.Session`.

    The session is a
    :class:`~terp.core._internal.session_guard.WriteGuardedSession`: persistence is
    refused outside the audited ``BaseService`` chokepoint (``add`` / ``commit`` / a
    DML ``execute`` raise
    :class:`~terp.core._internal.session_guard.UnauditedWriteError`), so a module
    cannot write past the audit trail. Reads are unaffected.
    """
    with WriteGuardedSession(get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


__all__ = ["SessionDep", "get_session"]
