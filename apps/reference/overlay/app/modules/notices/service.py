"""``notices`` services — CRUD is inherited from ``BaseService`` (audited, OCC, scoped)."""

from __future__ import annotations

from sqlmodel import Session

from terp.core import AuditAction, BaseService

from terp.capabilities.mail import MailMessage, send_mail

from app.modules.notices.models import Notice, Snapshot
from app.modules.notices.schemas import (
    NoticeCreate,
    NoticeUpdate,
    SnapshotCreate,
    SnapshotUpdate,
)


class NoticeService(BaseService[Notice, NoticeCreate, NoticeUpdate]):
    model = Notice

    def _after_write(self, session: Session, entity: Notice, action: AuditAction) -> None:
        """Mail a new notice to its recipient, inside the write that created it.

        ``send_mail`` only enqueues the capability's ``MAIL_SEND`` job on this session, so
        with the durable outbox wired the mail commits or rolls back with the notice, and
        ``terp jobs worker`` delivers it afterwards.
        """
        super()._after_write(session, entity, action)
        if action is AuditAction.CREATED:
            send_mail(
                session,
                MailMessage(to=[entity.recipient], subject=entity.title, text=entity.body),
            )


class SnapshotService(BaseService[Snapshot, SnapshotCreate, SnapshotUpdate]):
    model = Snapshot
    append_only = True
