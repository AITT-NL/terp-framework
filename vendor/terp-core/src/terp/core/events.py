"""The event catalog: a typed, NO-DRIFT event bus seam (an *optional* feature).

Unlike audit — a mandatory Tier-A control that may never be silently absent — the
event bus is an **optional product feature** (design §3.2 / §10): an app that
declares no events simply has none, with no ceremony. What the framework *does*
guarantee is **no drift**: every emitted or subscribed event is a registered,
typed :class:`EventDefinition` — never a bare string. A module references catalog
constants; it can neither invent an event name nor emit one the control plane has
not declared.

Layering mirrors the audit seam. ``terp.core`` (layer 0) must not depend on a
capability, so this module defines only the **seam**: the typed
:class:`EventDefinition` / :class:`EventCatalog` / :class:`EventEnvelope`, and an
:func:`emit` chokepoint whose **default dispatcher does nothing** (events go
nowhere until a dispatcher is installed). The in-process handler registry and the
synchronous dispatcher are the opt-in ``terp.capabilities.eventbus`` capability,
installed by ``create_app`` (just as ``terp-cap-audit`` fills the audit sink).

Two-layer enforcement of the no-drift guarantee:

* **Runtime (fail closed).** :func:`emit` rejects an :class:`EventDefinition` that
  is not the registered catalog entry — an unknown name *or* a same-name shadow
  (a look-alike with a different payload schema or visibility) — with an
  :class:`EventError`, and ``create_app`` boot-validates every ``ModuleSpec.emits``
  / ``subscribes`` against the catalog (an undeclared reference fails the boot).
* **Build time.** The ``terp.arch`` ``events_reference_catalog`` rule forbids a
  bare-string or inline-literal event anywhere ``emit`` / ``subscribe`` /
  ``ModuleSpec`` names one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlmodel import Session

from terp.core.logging import get_request_id


def _is_dotted_token(value: str) -> bool:
    """True for dotted authority/event names like ``notes.note.created``."""
    if not value:
        return False
    return all(
        part and part.replace("_", "").replace("-", "").isalnum()
        for part in value.split(".")
    )


class EventVisibility(str, Enum):
    """Who may see an event's payload (a typed object, never a bare string).

    The axis an outward relay/broadcaster MUST check before surfacing a payload. It
    is **advisory metadata, not yet an enforced gate**: the in-process bus relays only
    to backend handlers, so no outward relay exists to enforce it today — a future
    realtime/broker adapter is responsible for honoring it (failing closed on a
    non-``PUBLIC`` payload).
    """

    PUBLIC = "public"  # safe to surface outward (e.g. a realtime hint)
    INTERNAL = "internal"  # backend handlers only
    RESTRICTED = "restricted"  # never relayed verbatim (may carry PII/secrets)


@dataclass(frozen=True)
class EventDefinition:
    """A typed event contract: a namespaced *name*, a *payload schema*, *visibility*.

    The only thing :func:`emit` and ``subscribe`` accept — so every event has a
    validated payload model and an explicit visibility, and a module references a
    declared constant rather than minting a string. Declare these once in the
    control plane's event catalog.
    """

    name: str
    payload_schema: type
    visibility: EventVisibility = EventVisibility.INTERNAL

    def __post_init__(self) -> None:
        if not _is_dotted_token(self.name):
            raise ValueError(
                f"EventDefinition.name must be a dotted token, got {self.name!r}"
            )
        if not hasattr(self.payload_schema, "model_validate"):
            raise TypeError(
                f"EventDefinition.payload_schema must be a model type with "
                f"model_validate (e.g. a BaseSchema), got {self.payload_schema!r}"
            )


@dataclass(frozen=True)
class EventEnvelope:
    """One emitted event fact: the validated payload plus request correlation.

    Built centrally by :func:`emit` from an :class:`EventDefinition` and the
    request-scoped context, then handed to the active dispatcher; a handler never
    assembles one by hand.
    """

    name: str
    visibility: EventVisibility
    payload: Mapping[str, Any]
    request_id: str | None = None


@dataclass(frozen=True)
class EventCatalog:
    """The central registry of every :class:`EventDefinition` an app may emit.

    Optional by design: the default is **empty** (the feature is inactive). When
    events are used, this is the single source of truth they reference — a module
    cannot emit or subscribe to anything not declared here.
    """

    events: Sequence[EventDefinition] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        events = tuple(self.events)
        by_name: dict[str, EventDefinition] = {}
        for definition in events:
            if definition.name in by_name:
                raise ValueError(f"duplicate event declaration: {definition.name!r}")
            by_name[definition.name] = definition
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "_by_name", by_name)

    @classmethod
    def default(cls) -> EventCatalog:
        """The compatibility catalog: empty — the event bus is inactive."""
        return cls()

    def has_name(self, name: str) -> bool:
        """Return whether an event with *name* is registered."""
        return name in self._by_name

    def get(self, name: str) -> EventDefinition | None:
        """Return the canonical definition registered for *name* (or ``None``)."""
        return self._by_name.get(name)

    def has_event(self, definition: EventDefinition) -> bool:
        """Return whether *definition* is the canonical one registered for its name.

        Matched by **value**, not just by name: a same-name definition with a
        different payload schema or visibility is a *shadow* and is rejected, so
        the catalog stays the one source of truth (no drift through a look-alike).
        """
        return self._by_name.get(definition.name) == definition

    def missing_events(
        self, definitions: Iterable[EventDefinition]
    ) -> tuple[EventDefinition, ...]:
        """Every definition not registered in this catalog."""
        return tuple(d for d in definitions if not self.has_event(d))

    def names(self) -> tuple[str, ...]:
        """The registered event names, in declaration order."""
        return tuple(d.name for d in self.events)


class EventError(RuntimeError):
    """Raised when :func:`emit` is given an event that is not the registered catalog entry.

    Covers both an unknown name and a same-name shadow (different schema or
    visibility) — either way the emit is fail-closed.
    """


# A dispatcher delivers one already-validated envelope (e.g. to in-process
# handlers, or — later — a durable outbox) inside the caller's transaction. The
# default does nothing: events are inactive until a capability installs one.
EventDispatcher = Callable[[Session, EventEnvelope, EventDefinition], None]


def _noop_dispatcher(
    session: Session, envelope: EventEnvelope, definition: EventDefinition
) -> None:
    """The default dispatcher: events are inactive, so nothing is delivered."""


_active_catalog: EventCatalog = EventCatalog.default()
_active_dispatcher: EventDispatcher = _noop_dispatcher


def configure_events(
    catalog: EventCatalog, *, dispatcher: EventDispatcher | None = None
) -> None:
    """Install the active event *catalog* and *dispatcher* (called once by ``create_app``).

    *dispatcher* defaults to the no-op, so an app that declares a catalog but no
    event-bus capability still validates every :func:`emit` against the catalog —
    the event simply goes nowhere. A capability supplies a real dispatcher (e.g.
    in-process handlers) here.
    """
    global _active_catalog, _active_dispatcher
    _active_catalog = catalog
    _active_dispatcher = dispatcher if dispatcher is not None else _noop_dispatcher


def set_event_dispatcher(dispatcher: EventDispatcher) -> None:
    """Install just the event *dispatcher*, keeping the active catalog (capability hook)."""
    global _active_dispatcher
    _active_dispatcher = dispatcher


def reset_events_runtime() -> None:
    """Restore the empty catalog + no-op dispatcher (the composition-root/test baseline)."""
    global _active_catalog, _active_dispatcher
    _active_catalog = EventCatalog.default()
    _active_dispatcher = _noop_dispatcher


def _validate_payload(
    definition: EventDefinition, payload: Any | None
) -> dict[str, Any]:
    """Validate *payload* against the definition's schema and return a JSON dict."""
    schema = definition.payload_schema
    if payload is None:
        validated = schema()
    elif hasattr(payload, "model_dump"):
        validated = schema.model_validate(payload.model_dump())
    else:
        validated = schema.model_validate(payload)
    return dict(validated.model_dump(mode="json"))


def emit(
    session: Session,
    *,
    event: EventDefinition,
    payload: Any | None = None,
) -> EventEnvelope:
    """Emit one catalog *event* through the active dispatcher (fail closed).

    The single producer chokepoint: a service calls it next to its write, so HTTP
    routers, workers, and scripts all produce the same event stream. *event* is a
    typed :class:`EventDefinition` (never a string), and it must **match** its
    registered :class:`EventCatalog` entry — an unknown name *or* a same-name
    shadow (different schema/visibility) raises :class:`EventError` rather than
    drifting through. The payload is validated against the **catalog's** canonical
    definition and the request id is captured automatically. The dispatcher runs in
    the caller's transaction; this function never commits.
    """
    registered = _active_catalog.get(event.name)
    if registered is None:
        raise EventError(
            f"event {event.name!r} is not registered in the EventCatalog; "
            "declare it in the control plane's events before emitting it"
        )
    if registered != event:
        raise EventError(
            f"event {event.name!r} does not match its registered catalog "
            "definition (payload schema or visibility differ); reference the "
            "catalog constant rather than redefining it"
        )
    envelope = EventEnvelope(
        name=registered.name,
        visibility=registered.visibility,
        payload=_validate_payload(registered, payload),
        request_id=get_request_id(),
    )
    _active_dispatcher(session, envelope, registered)
    return envelope


__all__ = [
    "EventCatalog",
    "EventDefinition",
    "EventDispatcher",
    "EventEnvelope",
    "EventError",
    "EventVisibility",
    "configure_events",
    "emit",
    "reset_events_runtime",
    "set_event_dispatcher",
]
