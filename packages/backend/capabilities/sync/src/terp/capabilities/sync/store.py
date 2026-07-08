"""The one module that writes the append-only ``sync_record_log`` table.

Like the durable audit sink and the webhooks delivery log, a record-log row is infrastructure
at the base of the write stack: :class:`~terp.capabilities.sync.models.SyncRecordLog` is not a
``BaseTable`` (it is an immutable line), so it cannot route through ``BaseService`` — it
appends directly, riding the audited write unit so the INSERT joins whatever transaction is
open (its own outermost unit inside the ``SYNC_PULL`` job, which ``run_job`` opens at depth 0).
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlmodel import Session

# The append-only sync log must ride the audited write unit to commit; the scope primitive is
# _internal so an app module cannot open it to wave a write past the audit guard. This
# capability legitimately reaches it, exactly like the audit sink / outbox / webhooks stores.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: append-only sync log must ride the audited write unit; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.sync.models import SyncRecordLog

_MESSAGE_MAX: Final[int] = 2000


def clip_sync_message(value: str | None) -> str | None:
    """Strip NUL bytes and clamp a message to the ``message`` column bound."""
    if value is None:
        return None
    return value.replace("\x00", "")[:_MESSAGE_MAX]


def record_sync_log(
    session: Session,
    *,
    run_id: uuid.UUID,
    tenant_scope: str,
    tenant_id: uuid.UUID | None = None,
    entity_type: str,
    remote_id: str,
    action: str,
    message: str | None = None,
) -> SyncRecordLog:
    """Append one immutable record-log line inside the audited write unit."""
    log = SyncRecordLog(
        run_id=run_id,
        tenant_scope=tenant_scope,
        tenant_id=tenant_id,
        entity_type=entity_type,
        remote_id=remote_id,
        action=action,
        message=clip_sync_message(message),
    )
    with enter_write_unit() as outermost:
        session.add(log)  # arch-allow-mutations-emit-audit: append-only sync log at the base of the write stack (like the audit sink); SyncRecordLog is not a BaseTable, so it cannot route through BaseService
        if outermost:
            session.commit()  # arch-allow-mutations-emit-audit: a standalone log line is its own committed unit; a nested one defers to the outer BaseService commit
    return log


__all__ = ["clip_sync_message", "record_sync_log"]
