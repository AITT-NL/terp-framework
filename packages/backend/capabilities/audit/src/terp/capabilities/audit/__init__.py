"""terp.capabilities.audit — the durable sink behind the core audit seam.

``terp.core`` defines the audit *seam* (a typed :class:`~terp.core.AuditRecord`, the
:class:`~terp.core.AuditPolicy` registry, and an emit chokepoint whose default sink
only logs). This opt-in capability supplies the **durable** half: an append-only
:class:`AuditEvent` table, the :func:`persist_audit` sink, and a self-registering,
admin-only router to read the trail.

Wiring is a single composition-root line — ``create_app(...,
audit_sink=persist_audit)`` — after which **every** ``BaseService`` mutation in
every module is recorded with zero per-module code. It depends only on
``terp-core``: the sink consumes the public :class:`~terp.core.AuditRecord` /
:class:`~terp.core.AuditPolicy` surface, never a sibling capability.
"""

from __future__ import annotations

from terp.capabilities.audit.models import AuditEvent
from terp.capabilities.audit.router import module, router
from terp.capabilities.audit.schemas import AuditEventRead
from terp.capabilities.audit.service import list_audit_events
from terp.capabilities.audit.sink import persist_audit

__all__ = [
    "AuditEvent",
    "AuditEventRead",
    "list_audit_events",
    "module",
    "persist_audit",
    "router",
]
