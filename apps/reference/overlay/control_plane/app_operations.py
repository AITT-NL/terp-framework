"""What THIS app's own routes do — the half of the catalog the template never rewrites.

Declare an operation per route you build, and the catalog in
:mod:`control_plane.operations` folds them all in by splatting ``APP_OPERATIONS``.
"""

from __future__ import annotations

from terp.core import OperationDefinition

NOTICES_LIST = OperationDefinition(id="notices.list_notices", label="List the notices")
NOTICES_CREATE = OperationDefinition(
    id="notices.create_notice", label="Post a notice and mail it to its recipient"
)
NOTICES_GET = OperationDefinition(id="notices.get_notice", label="View a notice")
SNAPSHOTS_LIST = OperationDefinition(
    id="notices.list_snapshots", label="List the snapshots taken of the upstream"
)
SNAPSHOTS_REQUEST = OperationDefinition(
    id="notices.request_snapshot", label="Ask for a snapshot of the upstream now"
)

APP_OPERATIONS = (NOTICES_LIST, NOTICES_CREATE, NOTICES_GET, SNAPSHOTS_LIST, SNAPSHOTS_REQUEST)
