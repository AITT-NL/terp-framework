"""Subject expansion — the seam that lets grants apply to *collections* of subjects.

A :class:`~terp.capabilities.access.models.Grant` names a single ``subject_id``.
That subject is usually a user, but the column is FK-less **by design**: a grant
can just as well name a *group* of users (or any future principal-like subject).
This module is the seam that makes such indirect grants effective without the
access capability knowing who provides them:

* a higher-layer capability (e.g. ``terp-cap-groups``) **registers** a
  :data:`SubjectExpander` — a callable mapping one subject id to the extra
  subject ids it speaks for (a user's group ids);
* :meth:`~terp.capabilities.access.service.AccessService.has_permission` (the
  single hot path behind both ``require_permission`` and the kernel guard's
  ``permission_enforcer``) checks grants against the **expanded** subject set.

The plug-in direction mirrors the kernel's scope-predicate registry (ADR 0017):
the lower layer owns the registry and the check; the higher layer plugs in at
import time; the lower layer never imports the higher. With no expander
registered the set is exactly ``{subject_id}`` — the behaviour before this seam
existed. An expander that raises propagates: the guarded request fails closed
(500, no grant assumed) rather than silently narrowing to direct grants.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

from sqlmodel import Session

# Maps one subject to the additional subject ids whose grants it inherits
# (e.g. a user -> the ids of the groups the user belongs to).
SubjectExpander = Callable[[Session, uuid.UUID], Iterable[uuid.UUID]]

_expanders: list[SubjectExpander] = []


def register_subject_expander(expander: SubjectExpander) -> None:
    """Register *expander* (idempotent: re-registering the same callable is a no-op).

    Called at import time by the providing capability (the groups capability
    registers its membership expander when its package is imported by entry-point
    discovery), so installing the capability is all it takes.
    """
    if expander not in _expanders:
        _expanders.append(expander)


def reset_subject_expanders() -> None:
    """Clear the registry (test isolation for suites that register a throwaway expander)."""
    _expanders.clear()


def subject_ids_for(session: Session, subject_id: uuid.UUID) -> set[uuid.UUID]:
    """The full subject set whose grants *subject_id* holds: itself + every expansion."""
    subjects = {subject_id}
    for expander in _expanders:
        subjects.update(expander(session, subject_id))
    return subjects


__all__ = [
    "SubjectExpander",
    "register_subject_expander",
    "reset_subject_expanders",
    "subject_ids_for",
]
