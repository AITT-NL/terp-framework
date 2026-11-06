from typing import NamedTuple


class RouteSpec(NamedTuple):
    """A NamedTuple is frozen by construction, and holds a mutable dict anyway.

    Worse than the dataclass case in practice: a tuple is the shape people reach
    for precisely BECAUSE it is safe to use as a key or share freely, so the
    false guarantee travels further.
    """

    path: str
    handlers: dict[str, str]
