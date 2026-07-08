"""The object-level authorization registry — "may *this* principal act on *this* row?".

The kernel guard authorizes per **endpoint** (role rank by HTTP method, and a named
:class:`~terp.core.Permission` as a per-subject grant, ADR 0016), and the scope
registry (:mod:`terp.core.scoping`, ADR 0017) filters which rows a caller may
**see**. Neither answers the per-row *write* question — "may this caller edit
*this specific* record?" (ownership, team membership, a record-level ACL). That is
the classic object-level / BOLA gap, and consumers hand-rolled it in services, which
is easy to get wrong (and risks dropping the row scope). This module closes it with a
first-class seam.

Two deliberately separate mechanisms, split by *enforcement shape* (design §5):

* **Read visibility** is a *query filter* — :func:`~terp.core.register_scope_predicate`
  composes a ``WHERE`` clause into :meth:`~terp.core.BaseService.base_query`, so a
  non-visible row is simply never returned (it scales to ``list`` / pagination).
* **Write authorization** is a *post-load boolean* on the **already-loaded** row —
  this module. A boolean cannot paginate a list, so it is the wrong tool for read
  scoping; but it is exactly right for the per-row write gate, where the framework
  has the one target row in hand at the :class:`~terp.core.BaseService` write
  chokepoint.

Layering (ADR 0017's pattern): ``terp.core`` (layer 0) must not import a capability,
so richer policies (team membership, a shared-with ACL) plug in through
:func:`register_object_authz_predicate` — the kernel composes them without importing
them. The built-in owner check (a :class:`~terp.core.OwnedMixin` row may be written
only by its ``owner_id``) is the kernel's own, inlined here just as soft-delete is the
kernel's built-in row scope in :func:`~terp.core.scoping.apply_row_scope`.

The "no policy declared" path is safe and obvious: a model that composes neither
:class:`~terp.core.OwnedMixin` nor a registered predicate's trait is **allowed**
(:func:`apply_object_authz` returns ``True``) — object-authz is purely additive
per-model, so it never silently denies a model that never opted in. *Within* the
opt-in it is fail-closed: an owned row with a real owner denies a non-owner (or an
unauthenticated, actor-less) write.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlmodel import SQLModel

from terp.core.audit import AuditAction
from terp.core.base_models import OwnedMixin

# A predicate decides whether *actor* may perform *action* on the already-loaded
# *entity* (an instance of *model*). It returns ``True`` to allow and ``False`` to
# deny; it must **allow** (return ``True``) for a model it does not govern — it guards
# on the relevant mixin (``issubclass(model, ...)``), exactly like a
# :data:`~terp.core.scoping.ScopePredicate` no-ops for a model it does not own. The
# ``action`` (``UPDATED`` / ``DELETED``) lets a richer policy distinguish, e.g.,
# "the owner may edit but only an admin may delete" — the built-in owner check
# ignores it (the owner may perform any write).
ObjectAuthzPredicate = Callable[
    [type[SQLModel], SQLModel, uuid.UUID | None, AuditAction], bool
]

_object_authz_predicates: list[ObjectAuthzPredicate] = []


def register_object_authz_predicate(predicate: ObjectAuthzPredicate) -> None:
    """Register a per-row write-authorization predicate consulted on every guarded write.

    The seam a capability uses to plug an object-level policy (team membership, a
    record ACL) into the kernel **without the kernel importing it** — the write-side
    mirror of :func:`~terp.core.register_scope_predicate`. Registration is idempotent.
    :class:`~terp.core.BaseService` composes every registered predicate **on top of**
    the built-in owner check, fail-closed (``AND`` semantics): a write is allowed only
    if the built-in *and* every registered predicate allow it, so adding a predicate
    can only ever *narrow* who may write.
    """
    if predicate not in _object_authz_predicates:
        _object_authz_predicates.append(predicate)


def registered_object_authz_predicates() -> tuple[ObjectAuthzPredicate, ...]:
    """Every registered object-authz predicate, in registration order."""
    return tuple(_object_authz_predicates)


def apply_object_authz(
    model: type[SQLModel],
    entity: SQLModel,
    actor: uuid.UUID | None,
    action: AuditAction,
) -> bool:
    """Decide whether *actor* may perform *action* on the loaded *entity*.

    The single definition of "object-level write authorization", evaluated by
    :class:`~terp.core.BaseService` at the write chokepoint for an **existing** row
    (an ``UPDATED`` or ``DELETED`` action; a ``CREATED`` row has no prior owner to
    check — its owner is stamped instead). It composes, fail-closed:

    * the **built-in owner check** — a :class:`~terp.core.OwnedMixin` row whose
      ``owner_id`` is set may be written only by that owner; a different actor, or an
      actor-less (out-of-request / unauthenticated) write, is denied. An *unowned*
      row (``owner_id is None`` — e.g. created by a system job with no bound actor,
      the same best-effort boundary as the nullable actor stamp, ADR 0012) has no
      owner to protect, so the built-in does not restrict it;
    * then **every registered predicate** (``AND``) — any one returning ``False``
      denies.

    Returns ``True`` (allow) for a model that composes no ownership trait and matches
    no registered predicate — the safe, additive default. It is keyed off the
    *entity* (``isinstance``) rather than ``model`` so it is robust to a non-mapped
    stand-in (a hook spy), exactly as actor-stamping is (ADR 0012).
    """
    if (
        isinstance(entity, OwnedMixin)
        and entity.owner_id is not None
        and (actor is None or actor != entity.owner_id)
    ):
        return False
    return all(
        predicate(model, entity, actor, action)
        for predicate in _object_authz_predicates
    )


def reset_object_authz_predicates() -> None:
    """Clear all registered predicates (a test seam; capabilities re-register on import)."""
    _object_authz_predicates.clear()


__all__ = [
    "ObjectAuthzPredicate",
    "apply_object_authz",
    "register_object_authz_predicate",
    "registered_object_authz_predicates",
    "reset_object_authz_predicates",
]
