"""Example-app event catalog: the typed events — declared once.

The event bus is an *optional* product feature: declaring this catalog is what
turns it on for the example app. A single domain event, :data:`NOTE_CREATED`, is
emitted by the ``notes`` service next to its write and consumed by a ``tasks``
handler — demonstrating decoupled pub/sub through the central catalog. Every
``ModuleSpec.emits`` / ``subscribes`` reference is validated against this catalog at
boot, so an event name can never drift in as a bare string.
"""

from __future__ import annotations

import uuid

from sqlmodel import Field

from terp.core import BaseSchema, EventCatalog, EventDefinition, EventVisibility


class NoteCreatedPayload(BaseSchema):
    """The hint payload carried by :data:`NOTE_CREATED` (id + title only).

    Its fields are **auto-extracted from the Note row** by
    ``EventEmittingService`` (validated ``from_attributes``), so declaring them here
    is the whole payload contract — the module writes no payload-building code.
    """

    id: uuid.UUID
    title: str = Field(max_length=200)


NOTE_CREATED = EventDefinition(
    name="notes.note.created",
    payload_schema=NoteCreatedPayload,
    visibility=EventVisibility.INTERNAL,
)

event_catalog = EventCatalog([NOTE_CREATED])

__all__ = ["NOTE_CREATED", "NoteCreatedPayload", "event_catalog"]
