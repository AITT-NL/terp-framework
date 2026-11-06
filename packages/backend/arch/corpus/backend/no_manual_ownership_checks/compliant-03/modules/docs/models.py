from sqlmodel import Field

from terp.core import ActorStampedMixin, BaseTable


class Doc(BaseTable, ActorStampedMixin, table=True):
    title: str = Field(max_length=200)
