"""Operation declarations for the ``access`` capability's admin-only grants routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of granting or revoking a permission
without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

ACCESS_LIST_GRANTS = OperationDefinition(
    id="access.list_grants", label="List the permissions granted to someone"
)
ACCESS_CREATE_GRANT = OperationDefinition(
    id="access.create_grant", label="Grant a permission to someone"
)
ACCESS_DELETE_GRANT = OperationDefinition(
    id="access.delete_grant", label="Remove a granted permission"
)
ACCESS_GET_MODEL = OperationDefinition(
    id="access.get_model", label="See which roles exist and what each one may do"
)
ACCESS_GET_SUBJECT = OperationDefinition(
    id="access.get_subject",
    label="See what someone can do, and where each right comes from",
)
ACCESS_ASSIGN_MODULE_ROLE = OperationDefinition(
    id="access.assign_module_role",
    label="Give someone a role inside one module",
)
ACCESS_REVOKE_MODULE_ROLE = OperationDefinition(
    id="access.revoke_module_role",
    label="Take away someone's role inside one module",
)

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*ACCESS_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
ACCESS_OPERATIONS: tuple[OperationDefinition, ...] = (
    ACCESS_LIST_GRANTS,
    ACCESS_CREATE_GRANT,
    ACCESS_DELETE_GRANT,
    ACCESS_GET_MODEL,
    ACCESS_GET_SUBJECT,
    ACCESS_ASSIGN_MODULE_ROLE,
    ACCESS_REVOKE_MODULE_ROLE,
)

__all__ = [
    "ACCESS_ASSIGN_MODULE_ROLE",
    "ACCESS_CREATE_GRANT",
    "ACCESS_DELETE_GRANT",
    "ACCESS_GET_MODEL",
    "ACCESS_GET_SUBJECT",
    "ACCESS_LIST_GRANTS",
    "ACCESS_OPERATIONS",
    "ACCESS_REVOKE_MODULE_ROLE",
]
