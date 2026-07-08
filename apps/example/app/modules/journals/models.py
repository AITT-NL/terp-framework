"""``journals`` table model — an owner-scoped resource (only the owner may change a row).

Composes the kernel :class:`~terp.core.OwnedMixin`: ``BaseService`` stamps ``owner_id``
to the creating principal and then authorizes every update / delete of the row per-row,
so a non-owner write fails closed with 403 (ADR 0029) — the module writes no
ownership-check code (the ``no_manual_ownership_checks`` rule forbids it).

Read *visibility* is the separate, composable scope-registry seam (ADR 0017), and this
module is its **second divergent consumer** (ADR 0061; tenancy is the first): a
``visibility`` column ("shared" — the default, readable by anyone the role policy
admits — or "private" — hidden from everyone but the owner) drives the
consumer-registered ``_journal_visibility_predicate`` below. Importing this model
registers the predicate, exactly like ``TenantScopedMixin`` does for tenancy — two
strategies with nothing in common composing on the same kernel seam is the proof that
``terp.core`` is tenancy-agnostic.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel
from sqlmodel.sql.expression import SelectOfScalar

from terp.core import BaseTable, OwnedMixin, current_actor_id, register_scope_predicate

VISIBILITY_SHARED = "shared"
VISIBILITY_PRIVATE = "private"


class Journal(BaseTable, OwnedMixin, table=True):
    """A personal journal entry, owned by its creator.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from
    ``BaseTable``; ``owner_id`` from ``OwnedMixin`` (stamped from the request actor on
    create, then enforced as the per-row write gate). ``visibility`` opts a row out of
    shared reads: anything other than ``"shared"`` is only visible to its owner
    (fail closed — an unknown value never widens visibility).
    """

    __tablename__ = "journal"

    title: str = Field(max_length=200, index=True)
    entry: str = Field(default="", max_length=10_000)
    visibility: str = Field(default=VISIBILITY_SHARED, max_length=20, index=True)


def _journal_visibility_predicate(
    model: type[SQLModel], query: SelectOfScalar
) -> SelectOfScalar:
    """Hide another owner's private journals (registered centrally, ADR 0017 / 0061)."""
    if model is Journal:
        actor_id = current_actor_id()
        visibility_filter = Journal.visibility == VISIBILITY_SHARED
        if actor_id is not None:
            visibility_filter = visibility_filter | (Journal.owner_id == actor_id)  # arch-allow-no-manual-ownership-checks: this IS the consumer-registered read-visibility predicate ADR 0029 defers to — the write gate stays central; comparing owner_id here is the seam, not a bypass
        return query.where(visibility_filter)
    return query


register_scope_predicate(_journal_visibility_predicate)
