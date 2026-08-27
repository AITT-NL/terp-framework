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

__all__ = ["ACCESS_CREATE_GRANT", "ACCESS_DELETE_GRANT", "ACCESS_LIST_GRANTS"]
