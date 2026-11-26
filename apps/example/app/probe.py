"""The background probe: one job that does nothing but say it ran.

The example carries it so its production profile can be shown to run background work at
all. The probe schedule (``control_plane/schedules.py``) has ``terp jobs scheduler``
enqueue it every minute, ``terp jobs run ops.probe.run`` enqueues it by hand, and in both
cases ``terp jobs worker`` runs it from the durable outbox. The production smoke
(``.github/workflows/prod-smoke.yml``) holds both paths to a dispatched row. No user
starts it, so it runs as the control plane's system actor; it writes nothing.
"""

from __future__ import annotations

import logging

from terp.core import BaseSchema, JobContext, JobDefinition

logger = logging.getLogger("app.probe")


class ProbePayload(BaseSchema):
    """Empty on purpose: the probe needs nothing but to be run."""


def run_probe(ctx: JobContext, payload: ProbePayload) -> None:
    """Log that the probe ran; the dispatched outbox row is the proof."""
    logger.info("background probe ran (attempt %d)", ctx.attempt)


PROBE_RUN = JobDefinition(
    name="ops.probe.run",
    payload_schema=ProbePayload,
    handler=run_probe,
)

__all__ = ["PROBE_RUN", "ProbePayload", "run_probe"]
