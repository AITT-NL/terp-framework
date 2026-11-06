from typing import Optional

from terp.core import BaseSchema, NaiveMeansUtc

# Pydantic evaluates the string as a type, so a forward reference names the escape too.
Lenient = Optional["NaiveMeansUtc"]


class ReadingCreate(BaseSchema):
    taken_at: Lenient
