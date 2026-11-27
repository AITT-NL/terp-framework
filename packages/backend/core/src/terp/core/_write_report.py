"""The opt-in pytest report of committed ORM writes, including writes on plain sessions."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Generator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import InstanceState, SessionTransaction, UOWTransaction
from sqlalchemy.orm.attributes import NO_VALUE

from sqlmodel import Session

from terp.core._service_writes import _MANAGED_INPUT_COLUMNS, _service_write_observers


def _snapshot(value: Any) -> Any:
    # A binary column can hold a buffer. Copy the bytes without trying to pickle the view.
    if isinstance(value, (memoryview, bytearray)):
        return bytes(value)
    if isinstance(value, (dict, list, set)):
        return deepcopy(value)
    return value


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
    service_action: str = ""
    inserted: bool = False
    deleted: bool = False

    def apply(self, change: _Change) -> None:
        if change.operation in ("save", "remove"):
            self.service_action = change.operation
            self.expected.update(change.values)
            return
        self.inserted |= change.operation == "insert"
        self.deleted = change.operation == "delete"
        for key, value in change.previous.items():
            self.expected.setdefault(key, value)
        self.written.update(change.values)

    def differences(self) -> list[str]:
        if self.deleted:
            return [] if self.service_action == "remove" or self.inserted else ["<delete>"]
        if self.inserted and not self.service_action:
            return ["<insert>", *sorted(self.written)]
        return sorted(k for k, v in self.written.items() if v != self.expected.get(k, NO_VALUE))


def _findings(changes: list[_Change]) -> list[str]:
    rows: dict[Any, _Row] = defaultdict(_Row)
    models: dict[Any, type] = {}
    for change in changes:
        key = change.state.identity_key or change.state
        rows[key].apply(change)
        models[key] = change.state.class_
    findings = []
    for key, row in rows.items():
        if columns := row.differences():
            model = models[key]
            findings.append(f"{model.__module__}.{model.__qualname__} [{', '.join(columns)}]")
    return sorted(findings)


class WriteReport:
    """Keep flushes until their transaction commits. Discard a rolled-back savepoint."""

    def __init__(self) -> None:
        self.journals: dict[SessionTransaction, list[_Change]] = {}
        self.pending: list[list[str]] = []
        self.commits = 0
        self.reported: Counter[tuple[str, tuple[str, ...]]] = Counter()
        self.listeners = (
            ("after_flush", self._flushed),
            ("after_commit", self._committed),
            ("after_transaction_end", self._end),
        )
        for name, listener in self.listeners:
            event.listen(Session, name, listener)
        _service_write_observers.append(self._service_write)

    def close(self) -> None:
        _service_write_observers.remove(self._service_write)
        for name, listener in self.listeners:
            event.remove(Session, name, listener)
        self.journals.clear()

    def _end(self, session: Session, tx: SessionTransaction) -> None:
        self.journals.pop(tx, None)

    def _journal(self, session: Session) -> list[_Change]:
        tx = session.get_nested_transaction() or session.get_transaction()
        assert tx is not None
        return self.journals.setdefault(tx, [])

    def _service_write(self, session: Session, entity: object, operation: str) -> None:
        if not isinstance(session, Session):
            return  # A test double has no ORM transaction to observe.
        state = inspect(entity, raiseerr=False)
        if not isinstance(state, InstanceState) or state.session is not session:
            return  # A session double may accept a stand-in or leave a mapped row detached.
        # Reading state.dict keeps deferred and expired columns unloaded.
        values = {
            prop.key: _snapshot(state.dict[prop.key]) for prop in state.mapper.column_attrs
            if prop.key in state.dict and prop.key not in _MANAGED_INPUT_COLUMNS
        }
        self._journal(session).append(_Change(state, operation, values))

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
            for prop in state.mapper.column_attrs:
                key = prop.key
                history = state.attrs[key].history
                if not history.has_changes():
                    continue
                wrote_column = True
                if key not in _MANAGED_INPUT_COLUMNS:
                    values[key] = _snapshot(state.dict.get(key, NO_VALUE))
                    previous[key] = _snapshot(history.deleted[0]) if history.deleted else NO_VALUE
            if wrote_column or operation != "update":
                journal.append(_Change(state, operation, values, previous))

    def _committed(self, session: Session) -> None:
        changes = self._journal(session)
        nested = session.get_nested_transaction()
        if nested is not None:
            self.journals.setdefault(nested.parent, []).extend(changes)
        elif any(change.operation in ("insert", "update", "delete") for change in changes):
            self.pending.append(_findings(changes))

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        report = yield
        # TestReport properties travel to the controller when using pytest-xdist.
        report.user_properties.extend(("terp.write_commit", rows) for rows in self.pending)
        self.pending.clear()
        return report

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        for name, rows in report.user_properties:
            if name == "terp.write_commit":
                self.commits += 1
                if rows:
                    self.reported[report.nodeid, tuple(rows)] += 1

    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        flagged = self.reported.total()
        terminalreporter.write_sep("=", "terp write report")
        terminalreporter.write_line(
            f"{self.commits} ORM write transaction(s) committed, "
            f"{flagged} with changes outside a service save."
        )
        # Surface application models first even when frequently written framework tables
        # dominate the run. An application can itself write a framework model.
        for framework_only, heading in (
            (False, "Findings that include application models"),
            (True, "Findings on framework models only"),
        ):
            section = [
                (nodeid, rows, count) for (nodeid, rows), count in sorted(self.reported.items())
                if all(row.startswith(("terp.core.", "terp.capabilities.")) for row in rows)
                == framework_only
            ]
            if section:
                terminalreporter.write_line(heading)
                for nodeid, rows, count in section:
                    terminalreporter.write_line(f"  {nodeid} ({count}): {', '.join(rows)}")
