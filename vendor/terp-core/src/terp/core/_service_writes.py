"""Managed columns and observation of accepted service writes."""

from collections.abc import Callable

from sqlmodel import Session


# The pytest observer subscribes for the lifetime of a reporting run.
_service_write_observers: list[Callable[[Session, object, str], None]] = []


def _observe_service_write(session: Session, entity: object, operation: str) -> None:
    for record in _service_write_observers:
        record(session, entity, operation)


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
