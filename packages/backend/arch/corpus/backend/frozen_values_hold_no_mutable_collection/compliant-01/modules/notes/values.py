from dataclasses import dataclass
from collections.abc import Mapping


@dataclass(frozen=True)
class ImportPlan:
    """Frozen all the way down: the promise the type makes is the one it keeps."""

    name: str
    columns: tuple[str, ...]
    defaults: Mapping[str, str]
    tags: frozenset[str]
