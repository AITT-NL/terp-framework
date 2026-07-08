"""Serialize a :class:`~terp.core.JobEnvelope` to / from the JSON kwargs Celery carries.

Celery ships a JSON message body over its broker, so the whole envelope — including the
originating ``actor_id`` / ``tenant_id`` / ``request_id`` the kernel runner re-binds (the
jobs design's §7) — must round-trip through plain JSON scalars (``uuid.UUID`` → str,
``datetime`` → ISO-8601). No Python object or ORM row is ever sent (portability rule 2).

Kept adapter-local (a tiny duplicate of the outbox cap's identical helper) so this package
depends only on ``terp-core`` and never on a sibling capability — each engine adapter owns
how it frames the envelope for its own transport.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any

from terp.core import JobEnvelope


def job_envelope_to_kwargs(envelope: JobEnvelope) -> dict[str, Any]:
    """Flatten *envelope* to a JSON-safe dict for the Celery task's ``kwargs``.

    Serialized field-agnostically via :func:`dataclasses.asdict`, then the ``uuid`` /
    ``datetime`` fields are cast to JSON scalars — so it never hand-references the
    framework-managed ``tenant_id`` the envelope carries for the worker to re-bind (it is
    transport here, not a query scope filter).
    """
    data = asdict(envelope)
    data["actor_id"] = None if data["actor_id"] is None else str(data["actor_id"])
    data["tenant_id"] = None if data["tenant_id"] is None else str(data["tenant_id"])
    data["enqueued_at"] = data["enqueued_at"].isoformat()
    return data


def kwargs_to_job_envelope(data: Mapping[str, Any]) -> JobEnvelope:
    """Rebuild a :class:`~terp.core.JobEnvelope` from the Celery task's ``kwargs`` dict."""
    actor_id = data.get("actor_id")
    tenant_id = data.get("tenant_id")
    return JobEnvelope(
        name=data["name"],
        payload=dict(data["payload"]),
        idempotency_key=data.get("idempotency_key"),
        actor_id=uuid.UUID(actor_id) if actor_id is not None else None,
        tenant_id=uuid.UUID(tenant_id) if tenant_id is not None else None,
        request_id=data.get("request_id"),
        enqueued_at=datetime.fromisoformat(data["enqueued_at"]),
        attempt=int(data.get("attempt", 1)),
    )


__all__ = ["job_envelope_to_kwargs", "kwargs_to_job_envelope"]
