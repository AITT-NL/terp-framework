"""Operation declarations for the ``webhooks`` capability's admin-only routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of managing webhook subscriptions and
reviewing their delivery attempts without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

WEBHOOKS_LIST_SUBSCRIPTIONS = OperationDefinition(
    id="webhooks.list_subscriptions", label="List every webhook subscription"
)
WEBHOOKS_CREATE_SUBSCRIPTION = OperationDefinition(
    id="webhooks.create_subscription", label="Add a new webhook subscription"
)
WEBHOOKS_GET_SUBSCRIPTION = OperationDefinition(
    id="webhooks.get_subscription", label="View a webhook subscription's details"
)
WEBHOOKS_UPDATE_SUBSCRIPTION = OperationDefinition(
    id="webhooks.update_subscription", label="Edit a webhook subscription's details"
)
WEBHOOKS_DELETE_SUBSCRIPTION = OperationDefinition(
    id="webhooks.delete_subscription", label="Delete a webhook subscription"
)
WEBHOOKS_LIST_DELIVERIES = OperationDefinition(
    id="webhooks.list_webhook_deliveries",
    label="List the delivery attempts made to subscribed webhooks",
)

__all__ = [
    "WEBHOOKS_CREATE_SUBSCRIPTION",
    "WEBHOOKS_DELETE_SUBSCRIPTION",
    "WEBHOOKS_GET_SUBSCRIPTION",
    "WEBHOOKS_LIST_DELIVERIES",
    "WEBHOOKS_LIST_SUBSCRIPTIONS",
    "WEBHOOKS_UPDATE_SUBSCRIPTION",
]
