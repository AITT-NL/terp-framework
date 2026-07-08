"""Unit gate for the ``terp.core.events`` seam (the typed, NO-DRIFT event bus).

Exercises the catalog registry, the typed :class:`EventDefinition` validation, the
fail-closed :func:`emit` chokepoint (unregistered rejection, payload validation,
the default no-op vs. an installed dispatcher), and the control-plane boot
validation of ``emits`` / ``subscribes`` — the edge paths the end-to-end reference
tests do not all reach, so the framework holds 100% line coverage.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from terp.core import (
    AuditAction,
    BaseService,
    ControlPlane,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventError,
    EventVisibility,
    ModuleSpec,
    Policy,
    emit,
)
from terp.core.events import (
    EventDispatcher,
    configure_events,
    reset_events_runtime,
    set_event_dispatcher,
)
from terp.core.logging import request_id_ctx


class _Payload(BaseModel):
    id: str = ""
    label: str = ""


class _OtherPayload(BaseModel):
    note: str = ""


_CREATED = EventDefinition(
    name="things.thing.created",
    payload_schema=_Payload,
    visibility=EventVisibility.INTERNAL,
)

# Same name as _CREATED, but a different payload schema / visibility — a *shadow*
# the catalog must reject so the registered definition stays the source of truth.
_SCHEMA_SHADOW = EventDefinition(
    name="things.thing.created",
    payload_schema=_OtherPayload,
    visibility=EventVisibility.INTERNAL,
)
_VISIBILITY_SHADOW = EventDefinition(
    name="things.thing.created",
    payload_schema=_Payload,
    visibility=EventVisibility.RESTRICTED,
)


@pytest.fixture(autouse=True)
def _isolate_events() -> object:
    yield
    reset_events_runtime()


def _collecting_dispatcher() -> tuple[list[EventEnvelope], EventDispatcher]:
    seen: list[EventEnvelope] = []

    def dispatcher(
        session: object, envelope: EventEnvelope, definition: EventDefinition
    ) -> None:
        seen.append(envelope)

    return seen, dispatcher


class _SpySession:
    """A minimal session double that records the order of write calls."""

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


class _EmittingService(BaseService):
    """A service that emits a catalog event from the in-transaction ``_after_write`` hook."""

    def _after_write(self, session: object, entity: object, action: AuditAction) -> None:
        session.calls.append("after_write")  # type: ignore[attr-defined]
        emit(session, event=_CREATED, payload={"id": "1"})


# --------------------------------------------------------------------------- #
# EventDefinition / EventVisibility
# --------------------------------------------------------------------------- #
def test_event_definition_defaults_to_internal_visibility() -> None:
    definition = EventDefinition(name="a.b.c", payload_schema=_Payload)
    assert definition.visibility is EventVisibility.INTERNAL


def test_event_definition_rejects_a_non_dotted_name() -> None:
    with pytest.raises(ValueError, match="dotted token"):
        EventDefinition(name="not a token!", payload_schema=_Payload)
    with pytest.raises(ValueError, match="dotted token"):
        EventDefinition(name="", payload_schema=_Payload)


def test_event_definition_rejects_a_schema_without_model_validate() -> None:
    with pytest.raises(TypeError, match="model_validate"):
        EventDefinition(name="a.b.c", payload_schema=dict)


# --------------------------------------------------------------------------- #
# EventCatalog
# --------------------------------------------------------------------------- #
def test_default_catalog_is_empty_and_inactive() -> None:
    catalog = EventCatalog.default()
    assert catalog.events == ()
    assert catalog.names() == ()
    assert catalog.has_event(_CREATED) is False
    assert catalog.has_name("things.thing.created") is False


def test_catalog_indexes_events_by_name() -> None:
    catalog = EventCatalog([_CREATED])
    assert catalog.has_event(_CREATED) is True
    assert catalog.has_name("things.thing.created") is True
    assert catalog.names() == ("things.thing.created",)
    assert catalog.missing_events([_CREATED]) == ()


def test_catalog_rejects_duplicate_event_names() -> None:
    twin = EventDefinition(name="things.thing.created", payload_schema=_Payload)
    with pytest.raises(ValueError, match="duplicate event declaration"):
        EventCatalog([_CREATED, twin])


def test_catalog_reports_missing_events() -> None:
    other = EventDefinition(name="things.thing.deleted", payload_schema=_Payload)
    catalog = EventCatalog([_CREATED])
    assert catalog.missing_events([_CREATED, other]) == (other,)


def test_catalog_rejects_a_same_name_shadow() -> None:
    # A same-name look-alike (different schema or visibility) is not the canonical
    # entry, so the catalog rejects it — the registered definition stays the truth.
    catalog = EventCatalog([_CREATED])
    assert catalog.get("things.thing.created") is _CREATED
    assert catalog.get("nope.not.here") is None
    assert catalog.has_event(_SCHEMA_SHADOW) is False
    assert catalog.has_event(_VISIBILITY_SHADOW) is False
    assert catalog.missing_events([_VISIBILITY_SHADOW]) == (_VISIBILITY_SHADOW,)


# --------------------------------------------------------------------------- #
# emit (fail-closed chokepoint)
# --------------------------------------------------------------------------- #
def test_emit_rejects_an_unregistered_event() -> None:
    configure_events(EventCatalog.default())
    with pytest.raises(EventError, match="not registered in the EventCatalog"):
        emit(object(), event=_CREATED)  # type: ignore[arg-type]


def test_emit_rejects_a_same_name_shadow() -> None:
    # The name is registered, but the definition differs (visibility) — fail closed.
    configure_events(EventCatalog([_CREATED]))
    with pytest.raises(EventError, match="does not match its registered"):
        emit(object(), event=_VISIBILITY_SHADOW)  # type: ignore[arg-type]


def test_emit_validates_a_dict_payload_and_returns_an_envelope() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    token = request_id_ctx.set("req-123")
    try:
        envelope = emit(object(), event=_CREATED, payload={"id": "1", "label": "x"})  # type: ignore[arg-type]
    finally:
        request_id_ctx.reset(token)
    assert envelope.name == "things.thing.created"
    assert envelope.visibility is EventVisibility.INTERNAL
    assert envelope.payload == {"id": "1", "label": "x"}
    assert envelope.request_id == "req-123"
    assert seen == [envelope]


def test_emit_accepts_a_model_payload() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    envelope = emit(object(), event=_CREATED, payload=_Payload(id="7", label="seven"))  # type: ignore[arg-type]
    assert envelope.payload == {"id": "7", "label": "seven"}
    assert seen[0] is envelope


def test_emit_constructs_an_empty_payload_when_none() -> None:
    configure_events(EventCatalog([_CREATED]))
    envelope = emit(object(), event=_CREATED)  # type: ignore[arg-type]
    # The default no-op dispatcher delivers nowhere, but the envelope is built.
    assert envelope.payload == {"id": "", "label": ""}
    assert envelope.request_id is None


# --------------------------------------------------------------------------- #
# runtime configuration
# --------------------------------------------------------------------------- #
def test_configure_events_defaults_to_the_noop_dispatcher() -> None:
    # No dispatcher installed: emit validates but delivers nowhere (no error).
    configure_events(EventCatalog([_CREATED]))
    assert emit(object(), event=_CREATED).name == "things.thing.created"  # type: ignore[arg-type]


def test_set_event_dispatcher_keeps_the_active_catalog() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]))
    set_event_dispatcher(dispatcher)
    emit(object(), event=_CREATED, payload={"id": "1"})  # type: ignore[arg-type]
    assert len(seen) == 1


def test_reset_events_runtime_restores_the_empty_default() -> None:
    configure_events(EventCatalog([_CREATED]))
    reset_events_runtime()
    with pytest.raises(EventError):
        emit(object(), event=_CREATED)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# control-plane boot validation (no-drift)
# --------------------------------------------------------------------------- #
def test_control_plane_accepts_declared_emits_and_subscribes() -> None:
    plane = ControlPlane(events=EventCatalog([_CREATED]))
    spec = ModuleSpec(
        name="things", policy=Policy.default(), emits=[_CREATED], subscribes=[_CREATED]
    )
    assert plane.validation_errors([spec]) == ()


def test_control_plane_rejects_an_undeclared_emit() -> None:
    plane = ControlPlane(events=EventCatalog.default())
    spec = ModuleSpec(name="things", policy=Policy.default(), emits=[_CREATED])
    errors = plane.validation_errors([spec])
    assert any("things.thing.created" in error and "emits" in error for error in errors)


def test_control_plane_rejects_an_undeclared_subscription() -> None:
    plane = ControlPlane(events=EventCatalog.default())
    spec = ModuleSpec(name="things", policy=Policy.default(), subscribes=[_CREATED])
    errors = plane.validation_errors([spec])
    assert any(
        "things.thing.created" in error and "subscribes" in error for error in errors
    )


def test_control_plane_rejects_a_same_name_shadow_emit() -> None:
    # The catalog declares the canonical event; the module emits a same-name shadow.
    plane = ControlPlane(events=EventCatalog([_CREATED]))
    spec = ModuleSpec(name="things", policy=Policy.default(), emits=[_SCHEMA_SHADOW])
    errors = plane.validation_errors([spec])
    assert any(
        "things.thing.created" in error and "not registered" in error for error in errors
    )


# --------------------------------------------------------------------------- #
# the event rides the write transaction (BaseService._after_write hook)
# --------------------------------------------------------------------------- #
def test_after_write_emits_inside_the_write_before_commit() -> None:
    # The hook runs after the row is staged but before the commit, so the emit
    # rides the same transaction as the write (atomic).
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    spy = _SpySession()
    entity = SimpleNamespace(id=uuid.uuid4())
    _EmittingService()._save(spy, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert spy.calls.index("after_write") < spy.calls.index("commit")
    assert len(seen) == 1


def test_after_write_failure_aborts_the_write_before_commit() -> None:
    # A failing dispatcher/handler propagates out of _save before the commit, so a
    # broken side effect rolls the write back rather than committing without it.
    def boom(session: object, envelope: EventEnvelope, definition: EventDefinition) -> None:
        raise RuntimeError("handler failed")

    configure_events(EventCatalog([_CREATED]), dispatcher=boom)
    spy = _SpySession()
    entity = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(RuntimeError, match="handler failed"):
        _EmittingService()._save(spy, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert "commit" not in spy.calls
