"""The operation catalog: what each route *does*, as declared data (ADR 0102).

A route's method and path say how to call it; nothing said what it does for the
person calling it. The Studio's permission viewer had to render
``DELETE /api/v1/files/{file_id}  write  role:admin`` at a reader who cannot be
expected to translate that, and no part of the platform could claim every route was
explained.

An :class:`OperationDefinition` is that missing declaration: a stable id and a
source-language label, referenced from a route by :func:`terp.core.routing.operation`.

Layered exactly like the event catalog (ADR 0008), for the same reason. The *feature*
is optional — an app that declares no operations has none, with no ceremony, and the
default catalog is empty — while the **no-drift** guarantee is not: an operation named
at a route must be the registered catalog entry, so a module can neither invent one nor
reference one the control plane has not declared. What is additionally tunable here is
*coverage*: whether a route may decline to declare an operation at all
(:class:`OperationCoverage`).

Two things this deliberately is not:

* **It is not authorization.** A route's requirement comes from its module's ``Policy``
  and any route-level permission dependency, exactly as before. Declaring what a route
  does narrows nothing about who may call it — the same promise
  :func:`terp.core.routing.read_only` makes.
* **It is not a route DSL.** The definition carries an id and a label and nothing else.
  ADR 0006 permits an opt-in route factory and refuses a declarative route DSL as the
  only path; ADR 0102 §5 makes the boundary explicit — adding a routing or
  authorization field here is a decision that supersedes that ADR, not an increment.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

# One definition of the dotted-token shape rather than a third copy of it: event names
# already own this check and an operation id has exactly the same shape. (Role and
# permission names use the single-token form in ``terp.core.permissions``, which is a
# different shape, so it is deliberately not reused here.)
from terp.core.events import _is_dotted_token


class OperationCoverage(str, Enum):
    """How strictly an app requires its routes to declare an operation.

    Coverage is a per-app choice because the guarantee it buys differs per app, while
    the no-drift guarantee below it is never optional. ``STRICT`` is the state in which
    the platform can say every route is explained; it is opt-in because making it the
    default would refuse the boot of every app that upgraded without annotating, and
    an app whose only consumer is its own frontend may legitimately not want it.
    """

    #: Declarations are honored where present and never required (the default).
    OFF = "off"
    #: Undeclared routes are reported for a view to surface, and the boot proceeds.
    WARN = "warn"
    #: A mounted route with no declared operation fails the boot.
    STRICT = "strict"


@dataclass(frozen=True)
class OperationDefinition:
    """What one route does, as a stable *id* plus a source-language *label*.

    ``id`` is the translation key and the identity: dotted, like an event name
    (``files.delete``). ``label`` is the fallback text shown when no translation for
    the active language is available — the shape ``@terpjs/react-core`` already uses
    for translatable UI text, so no declaration names a language and adding one is a
    new catalog rather than a change to every call site.
    """

    id: str
    label: str

    def __post_init__(self) -> None:
        if not _is_dotted_token(self.id):
            raise ValueError(
                f"OperationDefinition.id must be a dotted token, got {self.id!r}"
            )
        if not self.label.strip():
            raise ValueError(
                f"OperationDefinition.label must say what the route does, got "
                f"{self.label!r} for {self.id!r}"
            )


@dataclass(frozen=True)
class OperationCatalog:
    """The registry of every :class:`OperationDefinition` an app's routes may declare.

    Optional by design: the default is **empty**, which means the feature is inactive
    and every route's label falls back to what can be derived from its name. When
    operations are used this is the single source of truth they reference.
    """

    operations: Sequence[OperationDefinition] = field(default_factory=tuple)
    coverage: OperationCoverage = OperationCoverage.OFF

    def __post_init__(self) -> None:
        operations = tuple(self.operations)
        by_id: dict[str, OperationDefinition] = {}
        for definition in operations:
            if definition.id in by_id:
                raise ValueError(f"duplicate operation declaration: {definition.id!r}")
            by_id[definition.id] = definition
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "_by_id", by_id)

    @classmethod
    def default(cls) -> OperationCatalog:
        """The compatibility catalog: empty, with coverage off — the feature is inactive."""
        return cls()

    def has_id(self, operation_id: str) -> bool:
        """Whether an operation with *operation_id* is registered."""
        return operation_id in self._by_id

    def get(self, operation_id: str) -> OperationDefinition | None:
        """The canonical definition registered for *operation_id* (or ``None``)."""
        return self._by_id.get(operation_id)

    def has_operation(self, definition: OperationDefinition) -> bool:
        """Whether *definition* is the canonical entry registered for its id.

        Matched by **value**, not merely by id: a same-id definition carrying a
        different label is a *shadow*, and accepting it would let a route present one
        wording while the catalog documents another. The catalog stays the one source
        of truth, as it does for events.
        """
        return self._by_id.get(definition.id) == definition

    def missing_operations(
        self, definitions: Iterable[OperationDefinition]
    ) -> tuple[OperationDefinition, ...]:
        """Every definition that is not the registered entry for its id."""
        return tuple(d for d in definitions if not self.has_operation(d))

    def ids(self) -> tuple[str, ...]:
        """The registered operation ids, in declaration order."""
        return tuple(d.id for d in self.operations)


__all__ = ["OperationCatalog", "OperationCoverage", "OperationDefinition"]
