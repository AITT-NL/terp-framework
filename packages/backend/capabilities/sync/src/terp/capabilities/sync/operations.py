"""Operation declarations for the ``sync`` capability's read-only admin routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of viewing past synchronization runs,
one run's record-by-record activity, or the identity mappings between the two
connected systems, without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

SYNC_LIST_RUNS = OperationDefinition(
    id="sync.list_sync_runs", label="List the past synchronization runs"
)
SYNC_GET_RUN = OperationDefinition(
    id="sync.get_sync_run", label="View one synchronization run's details"
)
SYNC_LIST_RUN_LOGS = OperationDefinition(
    id="sync.list_sync_run_logs",
    label="List what happened to each record in one synchronization run",
)
SYNC_LIST_MAPPINGS = OperationDefinition(
    id="sync.list_sync_mappings",
    label="List how records are matched between the two connected systems",
)

__all__ = [
    "SYNC_GET_RUN",
    "SYNC_LIST_MAPPINGS",
    "SYNC_LIST_RUNS",
    "SYNC_LIST_RUN_LOGS",
]
