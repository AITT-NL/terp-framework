"""Validate the ORM changes in the outer SQLModel transaction before it commits."""

from contextlib import ExitStack
from functools import partial

from sqlalchemy import Connection, event
from sqlalchemy.orm import SessionTransaction, UOWTransaction
from sqlmodel import Session

from terp.core._write_journal import WriteJournal, _findings


class UnvalidatedWriteError(RuntimeError):
    """An ORM row differs from the last state accepted by its writer."""


def _begin_before_sqlite_savepoint(connection: Connection, name: str | None) -> None:
    # The stdlib driver's legacy mode can release a first SAVEPOINT as a real commit.
    # Start the parent transaction only when needed, preserving normal read locking.
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


class CommitValidation(WriteJournal):
    def __init__(self) -> None:
        super().__init__()
        self.committing: set[SessionTransaction] = set()
        self.refusals: dict[SessionTransaction, str] = {}
        self.sqlite_connections: dict[SessionTransaction, ExitStack] = {}
        self.validation_listeners = (
            ("before_commit", self._before_commit),
            ("after_flush_postexec", self._final_flush),
            ("after_begin", self._begin),
        )
        for name, listener in self.validation_listeners:
            event.listen(Session, name, listener)

    def _begin(self, session: Session, tx: SessionTransaction, connection: Connection) -> None:
        if tx.parent is None and connection.dialect.driver == "pysqlite":
            # Two sessions can share an externally managed Connection. Each owns
            # its listener for exactly the lifetime of its own transaction.
            listener = partial(_begin_before_sqlite_savepoint)
            event.listen(connection, "savepoint", listener)
            cleanup = self.sqlite_connections.setdefault(tx, ExitStack())
            cleanup.callback(event.remove, connection, "savepoint", listener)

    def _before_commit(self, session: Session) -> None:
        if session.in_nested_transaction():
            return  # A released savepoint contributes to the parent's journal.
        tx = session.get_transaction()
        if tx in self.refusals:
            raise UnvalidatedWriteError(self.refusals[tx])
        session.flush()  # arch-allow-mutations-emit-audit: the commit validator materializes pending ORM changes inside their owning transaction
        self._check(tx)
        self.committing.add(tx)

    def _final_flush(self, session: Session, flush: UOWTransaction) -> None:
        # A later commit listener can still stage work for SQLAlchemy's final flush.
        tx = session.get_transaction()
        if tx in self.committing:
            self._check(tx)

    def _check(self, tx: SessionTransaction) -> None:
        if rows := _findings(self.journals.get(tx, [])):
            message = "Unvalidated ORM write: " + ", ".join(rows)
            self.refusals[tx] = message
            raise UnvalidatedWriteError(message)

    def _end(self, session: Session, tx: SessionTransaction) -> None:
        self.committing.discard(tx)
        self.refusals.pop(tx, None)
        if cleanup := self.sqlite_connections.pop(tx, None):
            cleanup.close()
        super()._end(session, tx)

    def close(self) -> None:
        for name, listener in self.validation_listeners:
            event.remove(Session, name, listener)
        for cleanup in self.sqlite_connections.values():
            cleanup.close()
        self.sqlite_connections.clear()
        self.committing.clear()
        self.refusals.clear()
        super().close()
