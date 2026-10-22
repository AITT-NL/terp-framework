"""``notices`` manifest — the entire public surface; profile ``shared``."""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from terp.capabilities.mail import MAIL_SEND

from app.modules.notices.jobs import SNAPSHOT_TAKE
from app.modules.notices.router import router
from app.modules.notices.service import NoticeService, SnapshotService

module = ModuleSpec(
    name="notices",
    router=router,
    policy=Policy.default(),
    services=(NoticeService, SnapshotService),
    # Both jobs this module causes: the mail a new notice sends, and the snapshot its
    # schedule takes. Boot checks each against the control plane's job catalog.
    jobs=[MAIL_SEND, SNAPSHOT_TAKE],
)
