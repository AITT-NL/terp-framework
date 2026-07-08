"""The one module that writes the append-only ``webhook_delivery`` table.

Like the durable audit sink and the outbox store, a delivery row is infrastructure at the
base of the write stack: :class:`~terp.capabilities.webhooks.models.WebhookDelivery` is not
a ``BaseTable`` (it is an immutable attempt record), so it cannot route through
``BaseService`` — it appends directly, riding the audited write unit so the INSERT joins
whatever transaction is open. Inside the ``WEBHOOK_DELIVER`` job it is its **own** outermost
unit (``run_job`` resets the write scope to depth 0), so the attempt row **commits
immediately** and therefore survives the subsequent ``raise`` that signals the outbox to
retry — the failure is recorded *and* re-delivered.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlmodel import Session

# The append-only delivery log must ride the audited write unit to commit (atomically when
# nested, standalone otherwise); the scope primitive is _internal so an app module cannot
# open it to wave a write past the audit guard. This capability legitimately reaches it,
# exactly like the audit sink / outbox store at the base of the write stack.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: append-only delivery infra must ride the audited write unit; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.webhooks.models import WebhookDelivery

_ERROR_MAX: Final[int] = 2000


def _clip(value: str | None) -> str | None:
    """Strip NUL bytes and clamp an error message to the ``last_error`` column bound."""
    if value is None:
        return None
    return value.replace("\x00", "")[:_ERROR_MAX]


def record_delivery(
    session: Session,
    *,
    subscription_id: uuid.UUID,
    event: str,
    outcome: str,
    attempt: int,
    response_code: int | None = None,
    last_error: str | None = None,
) -> WebhookDelivery:
    """Append one immutable delivery-attempt row inside the audited write unit."""
    delivery = WebhookDelivery(
        subscription_id=subscription_id,
        event=event,
        outcome=outcome,
        attempt=attempt,
        response_code=response_code,
        last_error=_clip(last_error),
    )
    with enter_write_unit() as outermost:
        session.add(delivery)  # arch-allow-mutations-emit-audit: append-only delivery log at the base of the write stack (like the audit sink); WebhookDelivery is not a BaseTable, so it cannot route through BaseService
        if outermost:
            session.commit()  # arch-allow-mutations-emit-audit: a standalone delivery record is its own committed unit; a nested one defers to the outer BaseService commit
    return delivery


__all__ = ["record_delivery"]
