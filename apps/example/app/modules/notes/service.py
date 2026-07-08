"""``notes`` service — declares the model and its lifecycle events (no imperative emit).

CRUD is inherited from the kernel ``BaseService`` via ``EventEmittingService``: the
module **declares** an ``event_map`` and the framework emits ``NOTE_CREATED`` inside
the write's transaction (atomic with the row). The payload is auto-extracted from the
row by the event's schema (id + title), so there is no hand-written ``emit``, no
``super()``, and no action branching — the constrained, declarative module shape
(ADR 0009). Contrast ``tasks``, which still hand-overrides its read/delete points.
"""

from __future__ import annotations

from terp.capabilities.eventbus import EventEmittingService, LifecycleEventMap

from app.modules.notes.models import Note
from app.modules.notes.schemas import NoteCreate, NoteUpdate
from control_plane.events import NOTE_CREATED


class NoteService(EventEmittingService[Note, NoteCreate, NoteUpdate]):
    model = Note
    event_map = LifecycleEventMap(created=NOTE_CREATED)
