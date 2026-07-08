"""Filesystem discovery primitive (internal, composition-root use only).

A pure, side-effect-free walk over an app's domain roots. It imports no domain
code, so it is safe to call from low-level contexts (e.g. Alembic) without
triggering import side effects. The composition root (a later phase) builds
router/model/event wiring on top of this.
"""

from __future__ import annotations

import importlib.metadata
import pathlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from terp.core.module_spec import ModuleSpec

_CAPABILITY_ENTRY_POINT_GROUP = "terp.capabilities"

# Domain roots in dependency order (lowest layer first).
DEFAULT_DOMAIN_ROOTS: tuple[str, ...] = ("capabilities", "foundation", "modules")


class CapabilityDiscoveryError(RuntimeError):
    """A capability entry point could not be loaded or is invalid (fail closed at boot).

    Discovery is part of composition, so a broken, mistyped, or name-colliding
    capability must stop the boot loudly — never crash with a bare traceback, mount
    a shadowing duplicate, or vanish silently.
    """


@dataclass(frozen=True)
class DomainPackage:
    """Metadata for a single discovered domain package."""

    root: str
    name: str
    path: pathlib.Path
    import_path: str


def iter_domain_packages(
    app_root: str | pathlib.Path,
    *,
    package: str = "app",
    roots: Iterable[str] = DEFAULT_DOMAIN_ROOTS,
) -> list[DomainPackage]:
    """Return every domain package under *app_root*, grouped by root then sorted.

    Directories whose name starts with ``_`` (e.g. ``_registry``) and
    non-directories are skipped, keeping discovery deterministic.
    """
    base = pathlib.Path(app_root)
    packages: list[DomainPackage] = []
    for root in roots:
        root_dir = base / root
        if not root_dir.is_dir():
            continue
        for child in sorted(root_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            packages.append(
                DomainPackage(
                    root=root,
                    name=child.name,
                    path=child,
                    import_path=f"{package}.{root}.{child.name}",
                )
            )
    return packages


def iter_capability_specs(names: Sequence[str] | None = None) -> list[ModuleSpec]:
    """Load installed capability ``ModuleSpec`` entry points.

    Capabilities self-register by declaring a ``terp.capabilities`` entry point
    that resolves to a :class:`~terp.core.ModuleSpec`. This lets ``create_app``
    mount a capability's router (and register its models) without any edit to a
    composition root.

    When *names* is supplied, only those entry points' specs are returned. This
    keeps discovery profile-shaped: an app may install optional capability
    packages for libraries or tooling without exposing every installed routed
    surface. Every installed entry point in the group is still loaded and
    validated first — filtering selects what mounts, never what is checked —
    so the duplicate-name guard cannot be bypassed by a filtered profile.

    Fail-closed discovery: an entry point that fails to import, resolves to
    something other than a ``ModuleSpec``, collides on entry-point name, or
    collides on ``name`` with another capability raises
    :class:`CapabilityDiscoveryError` — so a broken or shadowing capability stops
    the boot loudly instead of crashing with a bare traceback, mounting a
    duplicate router, or silently disappearing.
    """
    wanted = set(names) if names is not None else None
    specs: list[ModuleSpec] = []
    entry_points_seen: dict[str, str] = {}
    provided_by: dict[str, str] = {}
    installed: set[str] = set()
    for entry_point in importlib.metadata.entry_points(group=_CAPABILITY_ENTRY_POINT_GROUP):
        if entry_point.name in entry_points_seen:
            raise CapabilityDiscoveryError(
                f"capability entry point name {entry_point.name!r} is provided by two "
                f"targets ({entry_points_seen[entry_point.name]!r} and {entry_point.value!r}); "
                "entry point names must be unique so a capability filter cannot mount "
                "multiple surfaces"
            )
        entry_points_seen[entry_point.name] = entry_point.value
        try:
            loaded = entry_point.load()
        except Exception as exc:  # any import-time failure must fail boot, not pass silently
            raise CapabilityDiscoveryError(
                f"capability entry point {entry_point.name!r} ({entry_point.value}) "
                f"failed to load: {exc}"
            ) from exc
        if not isinstance(loaded, ModuleSpec):
            raise CapabilityDiscoveryError(
                f"capability entry point {entry_point.name!r} ({entry_point.value}) must "
                f"resolve to a terp.core.ModuleSpec, got {type(loaded).__name__}"
            )
        if loaded.name in provided_by:
            raise CapabilityDiscoveryError(
                f"capability name {loaded.name!r} is provided by two entry points "
                f"({provided_by[loaded.name]!r} and {entry_point.name!r}); capability "
                "names must be unique so a router cannot be shadowed"
            )
        provided_by[loaded.name] = entry_point.name
        installed.add(entry_point.name)
        if wanted is None or entry_point.name in wanted:
            specs.append(loaded)
    if wanted is not None:
        missing = wanted - installed
        if missing:
            raise CapabilityDiscoveryError(
                "requested capability entry point(s) not installed: "
                + ", ".join(sorted(missing))
            )
    return sorted(specs, key=lambda spec: spec.name)


__all__ = [
    "DEFAULT_DOMAIN_ROOTS",
    "CapabilityDiscoveryError",
    "DomainPackage",
    "iter_capability_specs",
    "iter_domain_packages",
]
