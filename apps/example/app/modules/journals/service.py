"""``journals`` service — owner-scoped CRUD via the kernel ``BaseService``.

No ownership code lives here: because ``Journal`` composes
:class:`~terp.core.OwnedMixin`, ``BaseService`` stamps ``owner_id`` on create and
authorizes every update / delete of an existing row per-row (ADR 0029). The service
just declares the model — the per-row write gate is enforced centrally at the audited
chokepoint, on top of the module's coarse role policy.
"""

from __future__ import annotations

from terp.core import BaseService

from app.modules.journals.models import Journal
from app.modules.journals.schemas import JournalCreate, JournalUpdate


class JournalService(BaseService[Journal, JournalCreate, JournalUpdate]):
    model = Journal
