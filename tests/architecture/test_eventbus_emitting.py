"""Unit gate for the declarative ``EventEmittingService`` / ``LifecycleEventMap`` (ADR 0009).

Proves a module declares *which* event each write lifecycle emits — no ``super()``,
no imperative ``emit``, no action branching — and the event fires from the
in-transaction ``_after_write`` hook with a payload auto-extracted from the row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from terp.core import (
    AuditAction,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventVisibility,
)
from terp.core.events import EventDispatcher, configure_events, reset_events_runtime

from terp.capabilities.eventbus import EventEmittingService, LifecycleEventMap


class _NotePayload(BaseModel):
    id: uuid.UUID
    title: str


_CREATED = EventDefinition(
    name="notes.note.created", payload_schema=_NotePayload, visibility=EventVisibility.INTERNAL
)


@pytest.fixture(autouse=True)
def _isolate_events() -> Iterator[None]:
    yield
    reset_events_runtime()


def _collecting_dispatcher() -> tuple[list[EventEnvelope], EventDispatcher]:
    seen: list[EventEnvelope] = []

    def dispatcher(session: object, envelope: EventEnvelope, definition: EventDefinition) -> None:
        seen.append(envelope)
        if hasattr(session, "calls"):
            session.calls.append("emit")  # type: ignore[attr-defined]

    return seen, dispatcher


class _SpySession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add(self, entity: object) -> None:
        self.calls.append("add")

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def refresh(self, entity: object) -> None:
        self.calls.append("refresh")

    def delete(self, entity: object) -> None:
        self.calls.append("delete")


class _NoteService(EventEmittingService):
    event_map = LifecycleEventMap(created=_CREATED)


def test_lifecycle_event_map_for_action() -> None:
    mapping = LifecycleEventMap(created=_CREATED)
    assert mapping.for_action(AuditAction.CREATED) is _CREATED
    assert mapping.for_action(AuditAction.UPDATED) is None
    assert mapping.for_action(AuditAction.DELETED) is None


def test_emits_mapped_event_with_auto_extracted_payload() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    note_id = uuid.uuid4()
    entity = SimpleNamespace(id=note_id, title="hello")
    spy = _SpySession()
    _NoteService()._save(spy, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert len(seen) == 1
    # The payload is extracted from the row by the event's schema (id + title).
    assert seen[0].payload == {"id": str(note_id), "title": "hello"}
    # …and it rode the transaction: emitted before the commit.
    assert spy.calls.index("emit") < spy.calls.index("commit")


def test_no_emit_for_an_unmapped_action() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    entity = SimpleNamespace(id=uuid.uuid4(), title="x")
    _NoteService()._save(_SpySession(), entity, AuditAction.UPDATED)  # type: ignore[arg-type]
    assert seen == []


def test_event_payload_is_overridable_for_a_computed_payload() -> None:
    class _CustomService(EventEmittingService):
        event_map = LifecycleEventMap(created=_CREATED)

        def _event_payload(self, entity: object, definition: EventDefinition) -> object:
            return {"id": str(entity.id), "title": "OVERRIDDEN"}  # type: ignore[attr-defined]

    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    entity = SimpleNamespace(id=uuid.uuid4(), title="ignored")
    _CustomService()._save(_SpySession(), entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert seen[0].payload["title"] == "OVERRIDDEN"
