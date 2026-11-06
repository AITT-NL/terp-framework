from terp.core import BaseSchema, NaiveMeansUtc

# A name bound to the escape is the escape at each field that uses it.
Lenient = NaiveMeansUtc


class ReadingCreate(BaseSchema):
    taken_at: Lenient
    checked_at: Lenient | None = None
