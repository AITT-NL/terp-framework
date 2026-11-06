from terp import core


class ReadingCreate(core.BaseSchema):
    # Reached through the module, or quoted, it is the same escape.
    taken_at: core.NaiveMeansUtc
    checked_at: "core.NaiveMeansUtc | None" = None
