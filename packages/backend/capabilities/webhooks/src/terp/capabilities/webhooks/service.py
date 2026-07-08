"""Webhook services: owner-scoped subscription CRUD + append-only delivery reads.

``WebhookSubscriptionService`` builds on ``BaseService`` — ``WebhookSubscription`` composes
``OwnedMixin``, so the per-row write gate (only the owner may edit / delete a subscription)
is enforced centrally by the kernel. On top of that, the create / update chokepoints **seal
the signing secret at rest** (ADR 0076): the plaintext never reaches the row, so a database
leak alone cannot forge a delivery. The delivery log is append-only, so it exposes only
read paths.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, func, select

from terp.core import BaseService, PaginationParams

from terp.capabilities.webhooks.models import WebhookDelivery, WebhookSubscription
from terp.capabilities.webhooks.sealing import seal_secret
from terp.capabilities.webhooks.schemas import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)


class WebhookSubscriptionService(
    BaseService[WebhookSubscription, WebhookSubscriptionCreate, WebhookSubscriptionUpdate]
):
    model = WebhookSubscription

    def create(
        self, session: Session, data: WebhookSubscriptionCreate
    ) -> WebhookSubscription:
        """Create a subscription with its signing secret **sealed at rest** (ADR 0076)."""
        return super().create(
            session, data.model_copy(update={"secret": seal_secret(data.secret)})
        )

    def update(
        self, session: Session, entity_id: uuid.UUID, data: WebhookSubscriptionUpdate
    ) -> WebhookSubscription:
        """Update a subscription, sealing a rotated signing secret before it lands."""
        if data.secret is not None:
            data = data.model_copy(update={"secret": seal_secret(data.secret)})
        return super().update(session, entity_id, data)

    def active_for_event(self, session: Session, event: str) -> list[WebhookSubscription]:
        """Every active subscription registered for *event* — the fan-out lookup.

        Builds on the non-droppable ``base_query`` so the read keeps the framework's row
        scope. A webhook fan-out delivers to **all** owners' active subscriptions for the
        event, so this is intentionally not owner-filtered (ownership gates *writes*, not the
        server-side delivery fan-out).
        """
        return list(
            session.exec(
                self.base_query().where(
                    col(WebhookSubscription.event) == event,
                    col(WebhookSubscription.active).is_(True),
                )
            ).all()
        )


def list_deliveries(
    session: Session,
    *,
    pagination: PaginationParams,
    subscription_id: uuid.UUID | None = None,
) -> tuple[list[WebhookDelivery], int]:
    """One page of delivery attempts, newest first (optionally for one subscription)."""
    conditions = (
        [col(WebhookDelivery.subscription_id) == subscription_id]
        if subscription_id is not None
        else []
    )
    total = session.exec(
        select(func.count()).select_from(WebhookDelivery).where(*conditions)
    ).one()
    rows = session.exec(
        select(WebhookDelivery)
        .where(*conditions)
        .order_by(col(WebhookDelivery.created_at).desc(), col(WebhookDelivery.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


__all__ = ["WebhookSubscriptionService", "list_deliveries"]
