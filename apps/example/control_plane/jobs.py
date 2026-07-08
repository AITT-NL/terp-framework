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

from terp.core import JobCatalog

from terp.capabilities.webhooks import WEBHOOK_DELIVER

job_catalog = JobCatalog([WEBHOOK_DELIVER])

__all__ = ["job_catalog"]
