"""Owner-scoped admin router for webhooks: subscription CRUD + a read-only delivery log.

Self-registering (``module``): the kernel's entry-point discovery mounts it at
``/api/v1/webhooks`` with no composition-root edit. Webhooks are a privileged, SSRF-sensitive
outbound-network capability, so the policy requires ``ADMIN``; ``WebhookSubscription`` also
composes ``OwnedMixin``, so the **per-row** write gate (an admin may edit / delete only their
*own* subscription) is enforced centrally by ``BaseService`` — the routes carry no ownership
logic. The signing ``secret`` is supplied on create / update and is **never** returned
(``WebhookSubscriptionRead`` omits it). A target URL is SSRF-validated at the boundary
(:func:`validate_webhook_target`, 422). The delivery log is append-only, exposed read-only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import ADMIN, ModuleSpec, Page, PaginationDep, Policy, SessionDep

from terp.capabilities.webhooks.schemas import (
    WebhookDeliveryRead,
    WebhookSubscriptionCreate,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from terp.capabilities.webhooks.service import WebhookSubscriptionService, list_deliveries
from terp.capabilities.webhooks.ssrf import validate_webhook_target

router = APIRouter(tags=["webhooks"])
_service = WebhookSubscriptionService()


@router.get("/subscriptions", response_model=Page[WebhookSubscriptionRead])
def list_subscriptions(
    session: SessionDep, pagination: PaginationDep
) -> Page[WebhookSubscriptionRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[WebhookSubscriptionRead].of(
        [WebhookSubscriptionRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/subscriptions", response_model=WebhookSubscriptionRead, status_code=201)
def create_subscription(
    payload: WebhookSubscriptionCreate, session: SessionDep
) -> WebhookSubscriptionRead:
    validate_webhook_target(payload.target_url)
    return WebhookSubscriptionRead.model_validate(_service.create(session, payload))


@router.get("/subscriptions/{subscription_id}", response_model=WebhookSubscriptionRead)
def get_subscription(
    subscription_id: uuid.UUID, session: SessionDep
) -> WebhookSubscriptionRead:
    return WebhookSubscriptionRead.model_validate(_service.get(session, subscription_id))


@router.patch("/subscriptions/{subscription_id}", response_model=WebhookSubscriptionRead)
def update_subscription(
    subscription_id: uuid.UUID, payload: WebhookSubscriptionUpdate, session: SessionDep
) -> WebhookSubscriptionRead:
    if payload.target_url is not None:
        validate_webhook_target(payload.target_url)
    return WebhookSubscriptionRead.model_validate(
        _service.update(session, subscription_id, payload)
    )


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(subscription_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, subscription_id)


@router.get("/deliveries", response_model=Page[WebhookDeliveryRead])
def list_webhook_deliveries(
    session: SessionDep,
    pagination: PaginationDep,
    subscription_id: uuid.UUID | None = None,
) -> Page[WebhookDeliveryRead]:
    rows, total = list_deliveries(
        session, pagination=pagination, subscription_id=subscription_id
    )
    return Page[WebhookDeliveryRead].of(
        [WebhookDeliveryRead.model_validate(row) for row in rows], total, pagination
    )


module = ModuleSpec(
    name="webhooks",
    router=router,
    policy=Policy(read=ADMIN, write=ADMIN),
)


__all__ = ["module", "router"]
