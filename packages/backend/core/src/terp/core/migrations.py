"""terp.core.migrations — discover packaged migration trees (pure, Alembic-free).

Each table-owning package owns an **independent, linear** Alembic history with its
own ``alembic_version_<label>`` version table, rather than one shared multi-branch
graph (ADR 0027). A package opts in by either:

* declaring a ``terp.migrations`` entry point (a capability — e.g. the ``audit``
  capability declares ``audit = "terp.capabilities.audit"``), or
* shipping a ``migrations/`` directory inside an app module (``app/modules/<name>``).

This module resolves *where* those histories live and *which* package owns each. It
is a side-effect-free filesystem walk that imports **no Alembic and no domain
models** — only PEP 420 namespace parents are imported when locating a package — so
it is safe to call from an Alembic ``env.py`` and stays inside the layer-0 kernel
boundary. The Alembic integration itself lives in the separate ``terp-migrations``
package (which depends on this seam), keeping the kernel free of a heavy migration
dependency.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import pathlib
from collections.abc import Iterator
from dataclasses import dataclass

from terp.core._internal.discovery import iter_domain_packages

_MIGRATION_ENTRY_POINT_GROUP = "terp.migrations"


class MigrationDiscoveryError(RuntimeError):
    """A declared migration tree cannot be resolved, or two share a label (fail closed).

    Migration discovery is part of a deploy-critical path: a mistyped entry point,
    a package that is not importable, or two packages claiming the same version
    label (which would make them share an ``alembic_version_<label>`` table and
    corrupt each other's history) must stop loudly, never resolve to a partial or
    colliding set.
    """


@dataclass(frozen=True)
class MigrationTree:
    """One package's independent, linear migration history.

    ``label`` is unique across the app and names both the package's history and its
    ``alembic_version_<label>`` table, so two packages never share version state.
    ``import_path`` is the ownership prefix: the package's models live at
    ``<import_path>.models`` and a table is "owned" by this tree when its mapped
    class's module starts with this prefix (the Alembic ``env.py`` uses that to
    scope autogenerate to only this package's tables).
    """

    label: str
    import_path: str
    path: pathlib.Path

    @property
    def version_table(self) -> str:
        """The dedicated Alembic version table isolating this package's history."""
        return f"alembic_version_{self.label}"

    @property
    def models_module(self) -> str:
        """The dotted module whose import registers this package's tables."""
        return f"{self.import_path}.models"

    @property
    def versions_path(self) -> pathlib.Path:
        """The Alembic ``versions/`` directory holding this package's revisions."""
        return self.path / "versions"

    @property
    def has_revisions(self) -> bool:
        """True once this package's ``versions/`` directory exists (migrations initialised).

        Distinct from :attr:`has_revision_files`: the directory can exist while holding
        no revision script yet — e.g. a first ``make`` created it (or failed part-way) —
        which is *initialised* but **not** *runnable*. Only :attr:`has_revision_files`
        gates whether a tree is run by ``upgrade`` / ``status`` / ``check``.
        """
        return self.versions_path.is_dir()

    @property
    def has_revision_files(self) -> bool:
        """True once ``versions/`` holds at least one real revision script (it is runnable).

        A bare ``versions/`` directory with no revision is **not** runnable: a package
        whose ``make`` created the directory but authored no revision (or failed
        mid-author) must not be treated as migrated, or its empty history would report
        as *current* while its tables were never created (ADR 0027). Alembic revision
        files are hash-named (never underscore-prefixed), so ``__init__`` / ``__pycache__``
        artefacts are ignored.
        """
        versions = self.versions_path
        return versions.is_dir() and any(
            entry.is_file() and not entry.name.startswith("_")
            for entry in versions.glob("*.py")
        )


def _package_dir(import_path: str, *, label: str) -> pathlib.Path:
    """Locate *import_path*'s package directory without importing its body.

    ``find_spec`` imports only the PEP 420 namespace parents (``terp`` /
    ``terp.capabilities`` — no ``__init__`` side effects) to find the leaf's spec;
    the capability's own module is never executed, so discovery is safe to call
    from low-level contexts (Alembic, boot) without triggering import side effects.
    """
    try:
        spec = importlib.util.find_spec(import_path)
    except (ImportError, AttributeError, ValueError) as exc:
        raise MigrationDiscoveryError(
            f"migration entry point {label!r} -> {import_path!r} could not be located: {exc}"
        ) from exc
    if spec is None or not spec.submodule_search_locations:
        raise MigrationDiscoveryError(
            f"migration entry point {label!r} -> {import_path!r} is not an importable package"
        )
    return pathlib.Path(next(iter(spec.submodule_search_locations)))


def _entry_point_trees() -> Iterator[MigrationTree]:
    """Migration trees declared by installed capabilities (``terp.migrations`` group).

    A capability declares the owning package as the entry-point value (e.g.
    ``audit = "terp.capabilities.audit"``); this discovers its history even when the
    capability is a *library* cap with no router entry point (e.g. ``identity``).
    """
    for entry_point in importlib.metadata.entry_points(group=_MIGRATION_ENTRY_POINT_GROUP):
        import_path = entry_point.value.split(":", 1)[0].strip()
        package_dir = _package_dir(import_path, label=entry_point.name)
        yield MigrationTree(
            label=entry_point.name,
            import_path=import_path,
            path=package_dir / "migrations",
        )


def _app_module_trees(app_root: str | pathlib.Path, package: str) -> Iterator[MigrationTree]:
    """Migration trees shipped by app modules under ``<app_root>/modules/<name>``."""
    for domain_package in iter_domain_packages(app_root, package=package, roots=("modules",)):
        yield MigrationTree(
            label=domain_package.name,
            import_path=domain_package.import_path,
            path=domain_package.path / "migrations",
        )


def _validate_unique_labels(trees: list[MigrationTree]) -> dict[str, MigrationTree]:
    by_label: dict[str, MigrationTree] = {}
    for tree in trees:
        existing = by_label.get(tree.label)
        if existing is not None:
            raise MigrationDiscoveryError(
                f"migration label {tree.label!r} is declared twice "
                f"({existing.import_path} and {tree.import_path}); labels must be "
                "unique so two histories cannot share an alembic_version table"
            )
        by_label[tree.label] = tree
    return by_label


def _candidate_trees(
    app_root: str | pathlib.Path | None, package: str
) -> list[MigrationTree]:
    """Every *declared* tree (installed capabilities + app modules), unfiltered."""
    candidates: list[MigrationTree] = list(_entry_point_trees())
    if app_root is not None:
        candidates.extend(_app_module_trees(app_root, package))
    return candidates


def _sorted_unique(trees: list[MigrationTree]) -> list[MigrationTree]:
    """Validate labels are unique, then order capabilities-first then app modules, by label."""
    by_label = _validate_unique_labels(trees)
    return sorted(
        by_label.values(),
        key=lambda tree: (not tree.import_path.startswith("terp."), tree.label),
    )


def resolve_all_migration_trees(
    app_root: str | pathlib.Path | None = None, *, package: str = "app"
) -> list[MigrationTree]:
    """Every *declared* migration tree, whether or not it ships a revision yet.

    Unlike :func:`resolve_migration_trees` (which keeps only *runnable* trees), this
    includes a package that has declared its migration ownership but authored no
    revision so far. It is the discovery path for **model import / autogenerate
    validation**: a brand-new module's *first* cross-module foreign key only resolves
    when the referenced module's models are imported into the shared metadata, even
    though that module has no runnable history yet (ADR 0027). ``upgrade`` /
    ``downgrade`` / ``status`` / ``check`` deliberately use the runnable set instead.

    Raises :class:`MigrationDiscoveryError` if two trees share a label.
    """
    return _sorted_unique(_candidate_trees(app_root, package))


def resolve_migration_trees(
    app_root: str | pathlib.Path | None = None, *, package: str = "app"
) -> list[MigrationTree]:
    """Every *runnable* migration tree (installed capabilities + app modules).

    A tree is runnable once it ships at least one real revision file in ``versions/``
    (see :attr:`MigrationTree.has_revision_files`), so a capability or module that has
    declared its ownership — or whose ``versions/`` directory exists but holds no
    revision — is skipped: an empty history must never be run or reported as current.
    When *app_root* is given, app modules under ``<app_root>/modules/<name>`` are
    included too. Capabilities sort first (then app modules), each group by label, for
    a deterministic upgrade order — Terp's capabilities are FK-less leaves, so the
    order is never a correctness constraint.

    Raises :class:`MigrationDiscoveryError` if two trees share a label.
    """
    runnable = [
        tree for tree in _candidate_trees(app_root, package) if tree.has_revision_files
    ]
    return _sorted_unique(runnable)


def resolve_migration_target(
    label: str, app_root: str | pathlib.Path | None = None, *, package: str = "app"
) -> MigrationTree:
    """Resolve the single tree labeled *label* (for authoring a new revision).

    Unlike :func:`resolve_migration_trees`, this does not require the ``versions/``
    directory to exist yet — authoring the *first* revision creates it — so it can
    target a capability or app module that has declared its migration ownership but
    shipped no revision so far.
    """
    for tree in _entry_point_trees():
        if tree.label == label:
            return tree
    if app_root is not None:
        for tree in _app_module_trees(app_root, package):
            if tree.label == label:
                return tree
    raise MigrationDiscoveryError(
        f"no migration package labeled {label!r}; declare a terp.migrations entry "
        "point on the capability, or run from the app root for an app module"
    )


__all__ = [
    "MigrationDiscoveryError",
    "MigrationTree",
    "resolve_all_migration_trees",
    "resolve_migration_target",
    "resolve_migration_trees",
]
