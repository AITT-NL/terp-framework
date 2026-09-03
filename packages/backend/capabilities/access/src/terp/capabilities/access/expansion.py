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
from dataclasses import dataclass

from sqlmodel import Session

# Maps one subject to the additional subject ids whose grants it inherits
# (e.g. a user -> the ids of the groups the user belongs to).
SubjectExpander = Callable[[Session, uuid.UUID], Iterable["uuid.UUID | SubjectRef"]]


@dataclass(frozen=True)
class SubjectRef:
    """One expanded subject, with *why* it is in the set attached.

    An expander has always known the answer to "why is this subject in play?" and thrown it
    away on the way out: the groups expander looks up memberships and returns bare ids, so a
    report explaining an effective right had to re-derive the membership itself, and could
    only ever name subjects it had already fetched.

    Additive on purpose. An expander may still return plain ``uuid.UUID`` — the groups
    capability did for its whole life and apps will have their own — and
    :func:`subject_ids_for` projects ids either way, so nothing on the request path changes.
    Only a caller that wants the attribution asks for it, through
    :func:`subject_refs_for`.
    """

    id: uuid.UUID
    #: A stable slug for the *sort* of subject: ``group``, ``self``, or whatever an app's own
    #: expander names. Dispatched on by a view, so never prose.
    kind: str
    #: What to call it in an explanation, where the expander knows. ``None`` when it does not,
    #: which a view renders as the bare id rather than inventing a label.
    name: str | None = None


def _as_ref(value: uuid.UUID | SubjectRef) -> SubjectRef:
    """Normalise whatever an expander returned into an attributed ref."""
    if isinstance(value, SubjectRef):
        return value
    return SubjectRef(id=value, kind="subject", name=None)

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
    """The full subject set whose grants *subject_id* holds: itself + every expansion.

    The decision path. Ids only, and deliberately: an authorization check has no use for a
    label, and building one would put string work on every guarded request.
    """
    subjects = {subject_id}
    for expander in _expanders:
        subjects.update(_as_ref(value).id for value in expander(session, subject_id))
    return subjects


def subject_refs_for(session: Session, subject_id: uuid.UUID) -> tuple[SubjectRef, ...]:
    """The same set, attributed — the explanation path.

    Starts with the subject itself as ``self``, so a report can say "held directly" in the
    same vocabulary it says "via the group Engineering". Never called by the guard.
    """
    refs = [SubjectRef(id=subject_id, kind="self", name=None)]
    seen = {subject_id}
    for expander in _expanders:
        for value in expander(session, subject_id):
            ref = _as_ref(value)
            if ref.id not in seen:
                seen.add(ref.id)
                refs.append(ref)
    return tuple(refs)


__all__ = [
    "SubjectExpander",
    "SubjectRef",
    "register_subject_expander",
    "reset_subject_expanders",
    "subject_ids_for",
    "subject_refs_for",
]
