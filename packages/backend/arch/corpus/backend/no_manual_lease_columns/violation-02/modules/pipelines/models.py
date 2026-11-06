from datetime import datetime

from sqlmodel import Field
from terp.core import BaseTable


class PipelineRun(BaseTable, table=True):
    """The same defect in its other common spelling: a heartbeat stamp on the row.

    A reader still cannot tell "working" from "died", because nothing declares how long
    a gap in the heartbeat is allowed to be, and nothing walks the run back when it is.
    """

    __tablename__ = "pipeline_run"

    status: str = Field(max_length=16, index=True)
    heartbeat_at: datetime | None = None
