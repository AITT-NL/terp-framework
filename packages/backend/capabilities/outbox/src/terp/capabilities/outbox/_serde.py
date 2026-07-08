"""Serialize a :class:`JobEnvelope` / :class:`EventEnvelope` to and from the row payload.

The outbox stores the **whole envelope** as the row's JSON ``payload`` (not just the
business payload), so the worker can faithfully rebuild what crossed the producer's
chokepoint — including the originating ``actor_id`` / ``tenant_id`` / ``request_id``
the runner re-binds (the jobs design's §7). Everything here round-trips through plain
JSON scalars (``uuid.UUID`` -> str, ``datetime`` -> ISO-8601), so no Python object or
ORM row is ever persisted (portability rule 2).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any

from terp.core import EventEnvelope, EventVisibility, JobEnvelope


def _str_or_none(value: object | None) -> str | None:
    """``str(value)`` for a non-``None`` id/uuid, else ``None`` (JSON-safe)."""
    return None if value is None else str(value)


def job_envelope_to_payload(envelope: JobEnvelope) -> dict[str, Any]:
    """Flatten a :class:`JobEnvelope` to a JSON-safe dict for the ``payload`` column.

    Serialized field-agnostically via :func:`dataclasses.asdict` (then the ``uuid`` /
    ``datetime`` fields are cast to JSON scalars), so it never hand-references a
    field name — including the framework-managed ``tenant_id`` the envelope carries
    for the worker to re-bind (the design's §7), which is transport here, not a query
    scope filter.
    """
    data = asdict(envelope)
    data["actor_id"] = _str_or_none(data["actor_id"])
    data["tenant_id"] = _str_or_none(data["tenant_id"])
    data["enqueued_at"] = data["enqueued_at"].isoformat()
    return data


def payload_to_job_envelope(data: Mapping[str, Any]) -> JobEnvelope:
    """Rebuild a :class:`JobEnvelope` from a stored ``payload`` dict."""
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


def event_envelope_to_payload(envelope: EventEnvelope) -> dict[str, Any]:
    """Flatten an :class:`EventEnvelope` to a JSON-safe dict for the ``payload`` column."""
    return {
        "name": envelope.name,
        "visibility": envelope.visibility.value,
        "payload": dict(envelope.payload),
        "request_id": envelope.request_id,
    }


def payload_to_event_envelope(data: Mapping[str, Any]) -> EventEnvelope:
    """Rebuild an :class:`EventEnvelope` from a stored ``payload`` dict."""
    return EventEnvelope(
        name=data["name"],
        visibility=EventVisibility(data["visibility"]),
        payload=dict(data["payload"]),
        request_id=data.get("request_id"),
    )


__all__ = [
    "event_envelope_to_payload",
    "job_envelope_to_payload",
    "payload_to_event_envelope",
    "payload_to_job_envelope",
]
