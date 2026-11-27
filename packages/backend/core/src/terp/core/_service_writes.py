"""Shared ORM write observation and the columns managed by Terp services."""

from collections.abc import Callable

from sqlmodel import Session


_write_observers: list[Callable[[Session, object, str, tuple[str, ...]], None]] = []

# Framework-managed columns a client input must never set: BaseService assigns all
# of these centrally (the primary key + audit timestamps + the OCC ``version`` +
# the scope/actor/owner columns). ``create`` / ``update`` strip them from the inbound
# payload so an over-wide schema (or a hand-built dict) can never over-post
# (mass-assign) them -- e.g. forge ``owner_id`` to seize a record. The terp.arch
# ``input_schemas_exclude_managed_columns`` rule is the build-time half of this
# control; the two sets must stay in lockstep.
_MANAGED_INPUT_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "version",
        "deleted_at",
        "tenant_id",
        "created_by_id",
        "modified_by_id",
        "owner_id",
        "token_version",
    }
)
