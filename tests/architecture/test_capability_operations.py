"""A capability's operation set is exhaustive, exported, and grows with its routes.

The friction this closes (ADR 0126). A capability declares its operations inside its own
package and re-exports the constants one by one; an app folds them into the single
``OperationCatalog`` its control plane owns. Nothing held those two halves together, so a
release that added a route to a capability added an operation the app's catalog did not
have — and under ``OperationCoverage.STRICT`` that is not a warning, it is a refused boot
(``terp.core.app`` raises ``BootError``). The app's only repair was to hand-enumerate a
capability's internal route inventory, which is not a thing it can own or even see.

``<CAP>_OPERATIONS`` is the seam: one aggregate per capability, splatted into the catalog,
so the tuple grows with the router and the app's catalog grows with the tuple. That only
holds while the aggregate is **exhaustive**, which is what these tests are for. Without
them the aggregate is a second list to forget rather than a fix — the same maintenance
burden it exists to remove, one indirection further away.

Enumeration is by module introspection rather than by walking routers, and that is a
decision with evidence behind it rather than a convenience. ``auth`` and ``oidc`` publish
``build_*_router`` factories that need configuration to call, so there is no uniform
router to walk at all. Worse for a router-walking test, ``leases`` publishes *both*: a
plain ``router`` and a ``build_holder_router`` factory, and ``leases.send_heartbeat`` is
declared only on the factory's route — so walking the obvious export would have reported
that capability complete while missing an operation. Every capability's operations do live
in one ``operations.py``, so introspection covers all eleven with one rule and no
per-capability knowledge.
"""

from __future__ import annotations

import importlib
import pathlib
from types import ModuleType

import pytest

from terp.core import OperationCatalog, OperationDefinition

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CAPS = _REPO_ROOT / "packages" / "backend" / "capabilities"


def _capabilities_declaring_operations() -> tuple[str, ...]:
    """Every capability package that ships an ``operations.py``, read from disk.

    Read from the source tree rather than listed, so a capability that starts declaring
    operations is picked up by these tests without an edit here. That is the same drift
    guard ``test_every_built_capability_is_covered`` applies to the arch harness: a list
    would let a new capability ship an unaggregated operation set silently.
    """
    found = [
        child.name
        for child in sorted(_CAPS.iterdir())
        if child.is_dir()
        and (
            child / "src" / "terp" / "capabilities" / child.name / "operations.py"
        ).is_file()
    ]
    assert found, "no capability ships an operations.py — the glob or the layout moved"
    return tuple(found)


_DECLARING = _capabilities_declaring_operations()


def _operations_module(capability: str) -> ModuleType:
    return importlib.import_module(f"terp.capabilities.{capability}.operations")


def _aggregate_name(capability: str) -> str:
    return f"{capability.upper()}_OPERATIONS"


def _declared_constants(module: ModuleType) -> dict[str, OperationDefinition]:
    """Every module-scope ``OperationDefinition`` in *module*, by constant name."""
    return {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("_") and isinstance(value, OperationDefinition)
    }


@pytest.mark.parametrize("capability", _DECLARING)
def test_every_capability_with_operations_publishes_an_aggregate(capability: str) -> None:
    """The seam exists at all: a capability that declares operations exports the set.

    Parametrized off the source tree, so this is the test a new capability fails until it
    ships the aggregate — the reason an app can rely on splatting rather than checking
    whether this particular capability happens to offer one.
    """
    module = _operations_module(capability)
    name = _aggregate_name(capability)
    aggregate = getattr(module, name, None)
    assert aggregate is not None, (
        f"{capability} declares operations but publishes no {name}; an app folding this "
        "capability in would have to name each constant, which is the coupling ADR 0126 "
        "removes"
    )
    assert isinstance(aggregate, tuple), (
        f"{name} must be a tuple so it is splattable and immutable, got "
        f"{type(aggregate).__name__}"
    )
    assert all(isinstance(entry, OperationDefinition) for entry in aggregate)


@pytest.mark.parametrize("capability", _DECLARING)
def test_the_aggregate_holds_every_operation_the_capability_declares(
    capability: str,
) -> None:
    """Exhaustive, in both directions, which is the property the fix rests on.

    Missing entry: a release adds a route, its operation is absent from the aggregate, and
    a STRICT app's boot is refused again — exactly the failure ADR 0126 exists to end, now
    caught here instead of in a consumer's upgrade.

    Extra entry: the aggregate carries a definition the module does not declare as a
    constant, which in practice means one built inline inside the tuple. The tuple would
    then ship an operation that reading ``operations.py``'s constants does not reveal, and
    no route could reference it without constructing its own copy — the shadow
    ``has_operation`` refuses. Both directions are asserted because each catches a
    different mistake, and neither implies the other.
    """
    module = _operations_module(capability)
    declared = _declared_constants(module)
    aggregate = getattr(module, _aggregate_name(capability))

    missing = sorted(
        name for name, value in declared.items() if value not in aggregate
    )
    assert not missing, (
        f"{_aggregate_name(capability)} is missing {missing}; add each new operation to "
        "the aggregate, or an app that splats it silently loses the route"
    )

    surplus = [entry for entry in aggregate if entry not in declared.values()]
    assert not surplus, (
        f"{_aggregate_name(capability)} names {[e.id for e in surplus]}, which "
        f"terp.capabilities.{capability}.operations does not declare"
    )


@pytest.mark.parametrize("capability", _DECLARING)
def test_the_aggregate_declares_each_operation_once(capability: str) -> None:
    """No duplicates: ``OperationCatalog`` refuses a repeated id at construction.

    A duplicate inside the aggregate would therefore not be a cosmetic wart — it would
    raise ``ValueError`` in the app's own control plane, at import time, with the app
    unable to fix a tuple it does not own.
    """
    aggregate = getattr(_operations_module(capability), _aggregate_name(capability))
    ids = [entry.id for entry in aggregate]
    assert len(ids) == len(set(ids)), f"duplicate operation ids in {ids}"


@pytest.mark.parametrize("capability", _DECLARING)
def test_the_aggregate_is_reachable_from_the_capability_package(capability: str) -> None:
    """Exported from the package, and advertised in ``__all__``.

    An app imports from ``terp.capabilities.<name>``, never from the private
    ``operations`` submodule (``no_deep_imports`` is a rule of the Standard), so an
    aggregate that is only reachable inside the package is not reachable at all.
    """
    package = importlib.import_module(f"terp.capabilities.{capability}")
    name = _aggregate_name(capability)
    assert hasattr(package, name), (
        f"terp.capabilities.{capability} does not re-export {name}; an app cannot reach "
        "it without a deep import the Standard refuses"
    )
    assert name in package.__all__, f"{name} is missing from the package __all__"
    assert getattr(package, name) is getattr(_operations_module(capability), name)


def test_the_catalog_accepts_every_capability_aggregate_at_once() -> None:
    """The end-to-end shape an app actually writes: splat them all into one catalog.

    Each earlier test holds one aggregate to its own module. This one proves the eleven
    compose — no id collides across capabilities, so an app mounting all of them builds a
    catalog rather than hitting ``OperationCatalog``'s duplicate-id refusal. A collision
    here would be unfixable downstream, since neither tuple belongs to the app.
    """
    folded: list[OperationDefinition] = []
    for capability in _DECLARING:
        folded.extend(
            getattr(_operations_module(capability), _aggregate_name(capability))
        )

    catalog = OperationCatalog(operations=tuple(folded))
    assert len(catalog.operations) == len(folded)
    for operation in folded:
        assert catalog.has_operation(operation)
