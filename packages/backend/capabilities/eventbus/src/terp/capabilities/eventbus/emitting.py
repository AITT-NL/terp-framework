"""Declarative lifecycle → event emission: the ``EventEmittingService`` mixin.

The authoring-layer canon (ADR 0009): a module **declares** which catalog event
each write lifecycle (created / updated / deleted) emits, and the framework emits
it **inside the write's transaction** through the core
:meth:`~terp.core.BaseService._after_write` hook. The module writes no imperative
``emit`` call, **no ``super()``**, and no action branching — it declares an
``event_map`` and, by default, the payload is auto-extracted from the row by the
event's own schema::

    class NoteService(EventEmittingService[Note, NoteCreate, NoteUpdate]):
        model = Note
        event_map = LifecycleEventMap(created=NOTE_CREATED)

This is the declarative replacement for hand-overriding ``_after_write`` (or, worse,
``super().create()`` then ``emit`` post-commit). The base still owns the transaction;
the module only declares intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from sqlmodel import SQLModel, Session

from terp.core import AuditAction, BaseService, EventDefinition, emit
from terp.core.base_models import BaseTable, BaseUpdateSchema

ModelT = TypeVar("ModelT", bound=BaseTable)
CreateT = TypeVar("CreateT", bound=SQLModel)
UpdateT = TypeVar("UpdateT", bound=BaseUpdateSchema)


@dataclass(frozen=True)
class LifecycleEventMap:
    """Declarative ``created`` / ``updated`` / ``deleted`` → event mapping.

    Each value is a typed catalog :class:`~terp.core.EventDefinition` (the
    ``terp.arch`` ``events_reference_catalog`` rule forbids a bare string here);
    ``None`` (the default) means that lifecycle write emits nothing.
    """

    created: EventDefinition | None = None
    updated: EventDefinition | None = None
    deleted: EventDefinition | None = None

    def for_action(self, action: AuditAction) -> EventDefinition | None:
        """Return the event mapped to *action* (or ``None`` when unmapped)."""
        return {
            AuditAction.CREATED: self.created,
            AuditAction.UPDATED: self.updated,
            AuditAction.DELETED: self.deleted,
        }[action]


class EventEmittingService(BaseService[ModelT, CreateT, UpdateT]):
    """A :class:`~terp.core.BaseService` that emits a declared event per lifecycle write.

    Declare ``event_map`` once; ``create`` / ``update`` / ``delete`` then emit the
    mapped catalog event from the in-transaction ``_after_write`` hook, so the event
    is atomic with the write. The payload defaults to the event's ``payload_schema``
    validated against the row (the schema's fields declare what the event carries);
    override :meth:`_event_payload` for a computed payload.
    """

    event_map: ClassVar[LifecycleEventMap]

    def _after_write(self, session: Session, entity: ModelT, action: AuditAction) -> None:
        super()._after_write(session, entity, action)
        definition = self.event_map.for_action(action)
        if definition is None:
            return
        emit(session, event=definition, payload=self._event_payload(entity, definition))

    def _event_payload(self, entity: ModelT, definition: EventDefinition) -> Any:
        """The payload for *entity* — by default extracted from its attributes.

        The event's ``payload_schema`` is validated against the row, so the schema's
        declared fields determine what is carried. Override for a computed payload.
        """
        return definition.payload_schema.model_validate(entity, from_attributes=True)


__all__ = ["EventEmittingService", "LifecycleEventMap"]
