"""The job catalog: every background job this app may enqueue, declared once.

``MAIL_SEND`` is the mail capability's own job (a new notice sends one); ``SNAPSHOT_TAKE``
is the notices module's (the schedule enqueues it). The durable ``OutboxJobQueue`` wired
in ``app/main.py`` records each one atomically with the write that caused it, and ``terp
jobs worker`` delivers it off-request.
"""

from __future__ import annotations

from terp.core import JobCatalog

from terp.capabilities.mail import MAIL_SEND

from app.modules.notices.jobs import SNAPSHOT_TAKE

job_catalog = JobCatalog([MAIL_SEND, SNAPSHOT_TAKE])

__all__ = ["job_catalog"]
