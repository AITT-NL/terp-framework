"""Track accepted and flushed ORM values in their owning session transaction."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import InstanceState, SessionTransaction, UOWTransaction
from sqlalchemy.orm.attributes import NO_VALUE
from sqlmodel import Session

from terp.core._service_writes import _MANAGED_INPUT_COLUMNS, _write_observers
from terp.core.base_models import BaseTable
from terp.core.base_service import _json_column_fields


def _managed(state: InstanceState) -> frozenset[str]:
    return _MANAGED_INPUT_COLUMNS if issubclass(state.class_, BaseTable) else frozenset()


def _snapshot(value: Any) -> Any:
    # A binary column can hold a buffer. Copy the bytes without trying to pickle the view.
    if isinstance(value, (memoryview, bytearray)):
        return bytes(value)
    if isinstance(value, (dict, list, set)):
        return deepcopy(value)
    return value


class _JsonBoolean(Enum):
    FALSE = False
    TRUE = True


def _json_snapshot(value: Any) -> Any:
    # JSON booleans and numbers are distinct even though Python's True equals 1.
    if isinstance(value, bool):
        return _JsonBoolean(value)
    if isinstance(value, dict):
        return {key: _json_snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_snapshot(item) for item in value]
    return _snapshot(value)


@dataclass
class _Change:
    state: InstanceState
    operation: str
    values: dict[str, Any]
    previous: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Row:
    expected: dict[str, Any] = field(default_factory=dict)
    written: dict[str, Any] = field(default_factory=dict)
    accepted_action: str = ""
    accepted_insert: bool = False
    inserted: bool = False
    deleted: bool = False

    def apply(self, change: _Change) -> None:
        if change.operation in ("save", "create", "append", "remove", "fields"):
            self.accepted_insert |= change.operation in ("create", "append")
            if change.operation != "fields":
                self.accepted_action = change.operation
            self.expected.update(change.values)
            for key, value in change.previous.items():
                self.written.setdefault(key, value)
            return
        self.inserted |= change.operation == "insert"
        self.deleted = change.operation == "delete"
        for key, value in change.previous.items():
            self.expected.setdefault(key, value)
        self.written.update(change.values)

    def differences(self) -> list[str]:
        if self.deleted:
            cancelled_insert = self.inserted and not self.accepted_action
            return [] if self.accepted_action == "remove" or cancelled_insert else ["<delete>"]
        if self.accepted_action == "remove":
            return ["<delete>"]
        if self.accepted_insert and not self.inserted:
            return ["<insert>"]
        if self.inserted and not self.accepted_insert:
            return ["<insert>", *sorted(self.written)]
        return sorted(k for k, v in self.written.items() if v != self.expected.get(k, NO_VALUE))


def _findings(changes: list[_Change]) -> list[str]:
    rows: dict[Any, _Row] = {}
    lifetimes: list[tuple[type, _Row]] = []
    for change in changes:
        key = change.state.identity_key or change.state
        row = rows.get(key)
        if row is None or row.deleted:
            row = rows[key] = _Row()
            lifetimes.append((change.state.class_, row))
        row.apply(change)
    findings = []
    for model, row in lifetimes:
        if columns := row.differences():
            findings.append(f"{model.__module__}.{model.__qualname__} [{', '.join(columns)}]")
    return sorted(findings)


class WriteJournal:
    """Keep flushes until their transaction commits. Discard a rolled-back savepoint."""

    def __init__(self, on_commit: Callable[[list[str]], None] | None = None) -> None:
        self.on_commit = on_commit
        self.journals: dict[SessionTransaction, list[_Change]] = {}
        self.listeners = (
            ("after_flush", self._flushed),
            ("after_commit", self._committed),
            ("after_transaction_end", self._end),
        )
        for name, listener in self.listeners:
            event.listen(Session, name, listener)
        _write_observers.append(self._accepted)

    def close(self) -> None:
        _write_observers.remove(self._accepted)
        for name, listener in self.listeners:
            event.remove(Session, name, listener)
        self.journals.clear()

    def _end(self, session: Session, tx: SessionTransaction) -> None:
        self.journals.pop(tx, None)

    def _journal(self, session: Session) -> list[_Change]:
        tx = session.get_nested_transaction() or session.get_transaction()
        assert tx is not None
        return self.journals.setdefault(tx, [])

    def _accepted(
        self, session: Session, entity: object, operation: str, fields: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(session, Session):
            return  # A test double has no ORM transaction to observe.
        state = inspect(entity, raiseerr=False)
        if not isinstance(state, InstanceState) or state.session is not session:
            return  # A session double may accept a stand-in or leave a mapped row detached.
        # Reading state.dict keeps deferred and expired columns unloaded.
        if operation == "append" and not state.pending:
            return  # An append owns a new row only.
        if operation == "save" and state.pending:
            operation = "create"
        columns = fields if operation == "fields" else (prop.key for prop in state.mapper.column_attrs)
        managed = _managed(state)
        json_keys = _json_column_fields(state.class_)
        values = {
            key: _json_snapshot(state.dict[key]) if key in json_keys else _snapshot(state.dict[key]) for key in columns
            if key in state.dict and key not in managed
        }
        # A hook may restore the database value before the first flush. SQLAlchemy
        # then omits the column from the UPDATE, but the saved value still matters.
        previous = {}
        if state.has_identity:
            for key in values:
                history = state.attrs[key].history
                if key in json_keys and key in state.committed_state:
                    # The ORM may omit the UPDATE on Python equality. Keep the
                    # original JSON so the commit must still match the saved value.
                    previous[key] = _json_snapshot(state.committed_state[key])
                elif history.has_changes():
                    previous[key] = _snapshot(history.deleted[0]) if history.deleted else NO_VALUE
        self._journal(session).append(_Change(state, operation, values, previous))

    def _flushed(self, session: Session, flush: UOWTransaction) -> None:
        journal = self._journal(session)
        # The flush plan also includes FK synchronisation, cascades and partial flushes.
        # Histories are still available here and are reset immediately after this event.
        for state, (deleted, list_only) in flush.states.items():
            if list_only:
                continue
            operation = "update" if state.has_identity else "insert"
            if deleted:
                operation = "delete"
            values, previous = {}, {}
            wrote_column = False
            managed = _managed(state)
            json_keys = _json_column_fields(state.class_)
            for prop in state.mapper.column_attrs:
                key = prop.key
                history = state.attrs[key].history
                if not history.has_changes():
                    continue
                wrote_column = True
                if key not in managed:
                    snapshot = _json_snapshot if key in json_keys else _snapshot
                    values[key] = snapshot(state.dict.get(key, NO_VALUE))
                    previous[key] = snapshot(history.deleted[0]) if history.deleted else NO_VALUE
            if wrote_column or operation != "update":
                journal.append(_Change(state, operation, values, previous))

    def _committed(self, session: Session) -> None:
        changes = self._journal(session)
        nested = session.get_nested_transaction()
        if nested is not None:
            self.journals.setdefault(nested.parent, []).extend(changes)
        elif self.on_commit and changes:
            rows = _findings(changes)
            if rows or any(c.operation in ("insert", "update", "delete") for c in changes):
                self.on_commit(rows)
