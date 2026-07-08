"""``tasks`` event handlers — react to domain events from the central catalog.

Decoupled pub/sub in action: ``tasks`` subscribes to the ``notes`` module's
:data:`~control_plane.events.NOTE_CREATED` event **through the control-plane
catalog** — it never imports the sibling module. The in-process dispatcher invokes
this handler synchronously when a note is created. Importing this module (from
``module.py``) is what registers the subscription.
"""

from __future__ import annotations

import logging

from terp.core import EventEnvelope

from terp.capabilities.eventbus import subscribe

from control_plane.events import NOTE_CREATED

logger = logging.getLogger("app.modules.tasks")


@subscribe(NOTE_CREATED)
def on_note_created(envelope: EventEnvelope) -> None:
    """Log that a note was created — a placeholder cross-module reaction."""
    logger.info("tasks observed note created: %s", envelope.payload.get("title"))


__all__ = ["on_note_created"]
