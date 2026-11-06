import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from terp.core import ActorStampedMixin, BaseTable


class Decision(BaseTable, ActorStampedMixin, table=True):
    """One decision per reviewer per record, enforced where it cannot race.

    Uniqueness keyed on the actor is neither shape this rule refuses. It forges no
    trail, and it decides nothing about who may act on a row - it says whether a
    SECOND row may exist, which the ownership seam has nothing to say about. As a
    table constraint the column is named as a string, so no attribute access is
    involved, and the database rejects the duplicate insert that two concurrent
    requests would both get past a check-then-insert probe.
    """

    __table_args__ = (UniqueConstraint("record_id", "created_by_id"),)

    record_id: uuid.UUID = Field(index=True)
    verdict: str = Field(max_length=16)
