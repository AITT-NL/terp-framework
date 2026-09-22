"""Example-app job catalog: the typed background jobs — declared once.

Like the event catalog, declaring this catalog is what turns background work on for the
example app. It registers the webhooks capability's :data:`WEBHOOK_DELIVER` job so the
note-created webhook fan-out (see :mod:`app.webhooks`) can enqueue it through the typed
chokepoint; the durable ``OutboxJobQueue`` (wired in :mod:`app.main`) records each enqueued
job atomically with the business write, and ``terp jobs worker`` drains and delivers them
off-request. Every ``ModuleSpec.jobs`` reference is validated against this catalog at boot,
so a job name can never drift in as a bare string.
"""

from __future__ import annotations

import uuid

from terp.core import JobCatalog

from terp.capabilities.webhooks import WEBHOOK_DELIVER

#: The principal a job's writes are stamped with when no user originated the work.
#: Declaring it is not optional for an app with a job catalog: production refuses the
#: boot without one, because a background write whose ``created_by_id`` answers nobody
#: is the one answer a provenance column must not give (ADR 0125).
#:
#: A fixed constant is right *here* and would be wrong in the framework. This app is a
#: reference that has to boot in CI against an empty database, so it has no seeded
#: principal to point at, and the value being visible in its own control plane is the
#: point -- an app made a choice and can be asked about it. A platform-wide default
#: doing the same thing would apply to every app silently and resolve to no principal
#: anywhere, which is why ADR 0125 refuses one. A real deployment points this at a
#: service principal it can name in an audit review.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-0000000e5a01")

job_catalog = JobCatalog([WEBHOOK_DELIVER])

__all__ = ["SYSTEM_ACTOR_ID", "job_catalog"]
