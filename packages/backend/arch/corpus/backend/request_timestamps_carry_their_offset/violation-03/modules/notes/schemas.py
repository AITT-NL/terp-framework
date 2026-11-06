from terp.core import BaseSchema

from app.common.types import NaiveMeansUtc


class ReadingCreate(BaseSchema):
    # A re-export of the escape is the escape: the boundary steps aside for it all the same.
    taken_at: NaiveMeansUtc
