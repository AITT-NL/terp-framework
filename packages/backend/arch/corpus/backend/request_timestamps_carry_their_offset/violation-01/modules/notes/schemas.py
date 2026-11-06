from terp.core import BaseSchema, NaiveMeansUtc


class ReadingCreate(BaseSchema):
    # Reads a timestamp sent without an offset as UTC. Right only for a sender that is
    # known to send UTC; any other is stored off by its offset, and nothing says so.
    taken_at: NaiveMeansUtc
