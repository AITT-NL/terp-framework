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

from terp.core._internal.engine import get_engine, maintenance_engine
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


# `maintenance_engine` is re-exported rather than reached for: this module is the
# sanctioned seam onto the engine, and `terp.core._internal.engine` is the module its own
# docstring says nothing else may import. A maintenance engine is not a session and never
# serves a request -- `CREATE DATABASE` cannot run inside a transaction and is addressed
# at the server rather than at the application's database -- but it is still an engine,
# so it is handed out from the same place as the other one.
__all__ = ["SessionDep", "get_session", "maintenance_engine"]
