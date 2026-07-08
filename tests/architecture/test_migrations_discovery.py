"""The pure migration-discovery seam (``terp.core.migrations``).

Resolves each table-owning package's independent, linear Alembic history — from
installed capabilities (``terp.migrations`` entry points) and app modules shipping
a ``migrations/`` directory — without importing Alembic or any domain model. The
Alembic integration that consumes this seam lives in ``terp-migrations``.
"""

from __future__ import annotations

import pathlib

import pytest

from terp.core import migrations
from terp.core.migrations import (
    MigrationDiscoveryError,
    MigrationTree,
    resolve_all_migration_trees,
    resolve_migration_target,
    resolve_migration_trees,
)


class _FakeEntryPoint:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


class _FakeSpec:
    def __init__(self, locations: list[str] | None) -> None:
        self.submodule_search_locations = locations


def _patch_caps(
    monkeypatch: pytest.MonkeyPatch,
    entry_points: list[_FakeEntryPoint],
    dir_map: dict[str, pathlib.Path | None],
) -> None:
    monkeypatch.setattr(
        migrations.importlib.metadata, "entry_points", lambda *, group: list(entry_points)
    )

    def _fake_find_spec(import_path: str) -> _FakeSpec | None:
        located = dir_map[import_path]
        return _FakeSpec(None if located is None else [str(located)])

    monkeypatch.setattr(migrations.importlib.util, "find_spec", _fake_find_spec)


def _make_tree_dir(
    base: pathlib.Path, *, with_versions: bool, with_revision: bool = True
) -> pathlib.Path:
    base.mkdir(parents=True, exist_ok=True)
    if with_versions:
        versions = base / "migrations" / "versions"
        versions.mkdir(parents=True)
        if with_revision:
            (versions / "0001_init.py").write_text(
                "revision = '0001'\n", encoding="utf-8"
            )
    return base


def test_tree_properties() -> None:
    tree = MigrationTree(
        label="audit", import_path="terp.capabilities.audit", path=pathlib.Path("/x/migrations")
    )
    assert tree.version_table == "alembic_version_audit"
    assert tree.models_module == "terp.capabilities.audit.models"
    assert tree.versions_path == pathlib.Path("/x/migrations/versions")
    assert tree.has_revisions is False
    assert tree.has_revision_files is False


def test_resolve_caps_first_then_modules(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_dir = _make_tree_dir(tmp_path / "caps" / "audit", with_versions=True)
    access_dir = _make_tree_dir(tmp_path / "caps" / "access", with_versions=True)
    # Declares the entry point but ships no versions/ yet -> skipped as not runnable.
    eventbus_dir = _make_tree_dir(tmp_path / "caps" / "eventbus", with_versions=False)
    _patch_caps(
        monkeypatch,
        [
            _FakeEntryPoint("audit", "terp.capabilities.audit"),
            _FakeEntryPoint("access", "terp.capabilities.access"),
            _FakeEntryPoint("eventbus", "terp.capabilities.eventbus"),
        ],
        {
            "terp.capabilities.audit": audit_dir,
            "terp.capabilities.access": access_dir,
            "terp.capabilities.eventbus": eventbus_dir,
        },
    )
    app_root = tmp_path / "app"
    _make_tree_dir(app_root / "modules" / "notes", with_versions=True)
    (app_root / "modules" / "tasks").mkdir(parents=True)  # no migrations/ -> skipped

    trees = resolve_migration_trees(app_root, package="app")

    assert [tree.label for tree in trees] == ["access", "audit", "notes"]
    notes = trees[-1]
    assert notes.import_path == "app.modules.notes"
    assert notes.version_table == "alembic_version_notes"
    assert notes.has_revisions is True


def test_resolve_without_app_root_is_caps_only(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_dir = _make_tree_dir(tmp_path / "audit", with_versions=True)
    _patch_caps(
        monkeypatch,
        [_FakeEntryPoint("audit", "terp.capabilities.audit")],
        {"terp.capabilities.audit": audit_dir},
    )
    trees = resolve_migration_trees()
    assert [tree.label for tree in trees] == ["audit"]


def test_duplicate_label_fails_closed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap_dir = _make_tree_dir(tmp_path / "caps" / "notes", with_versions=True)
    _patch_caps(
        monkeypatch,
        [_FakeEntryPoint("notes", "terp.capabilities.notes")],
        {"terp.capabilities.notes": cap_dir},
    )
    app_root = tmp_path / "app"
    _make_tree_dir(app_root / "modules" / "notes", with_versions=True)

    with pytest.raises(MigrationDiscoveryError, match="declared twice"):
        resolve_migration_trees(app_root, package="app")


def test_entry_point_not_a_package_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_caps(
        monkeypatch,
        [_FakeEntryPoint("ghost", "terp.capabilities.ghost")],
        {"terp.capabilities.ghost": None},
    )
    with pytest.raises(MigrationDiscoveryError, match="not an importable package"):
        resolve_migration_trees()


def test_entry_point_unlocatable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        migrations.importlib.metadata,
        "entry_points",
        lambda *, group: [_FakeEntryPoint("boom", "terp.capabilities.boom")],
    )

    def _raise(import_path: str) -> None:
        raise ImportError("no such module")

    monkeypatch.setattr(migrations.importlib.util, "find_spec", _raise)
    with pytest.raises(MigrationDiscoveryError, match="could not be located"):
        resolve_migration_trees()


def test_resolve_target_for_capability(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No versions/ yet: a target is resolvable so the first revision can be authored.
    audit_dir = _make_tree_dir(tmp_path / "audit", with_versions=False)
    _patch_caps(
        monkeypatch,
        [_FakeEntryPoint("audit", "terp.capabilities.audit")],
        {"terp.capabilities.audit": audit_dir},
    )
    target = resolve_migration_target("audit")
    assert target.import_path == "terp.capabilities.audit"
    assert target.versions_path == audit_dir / "migrations" / "versions"


def test_resolve_target_for_app_module(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_caps(monkeypatch, [], {})
    app_root = tmp_path / "app"
    (app_root / "modules" / "billing").mkdir(parents=True)  # no migrations/ yet
    target = resolve_migration_target("billing", app_root, package="app")
    assert target.import_path == "app.modules.billing"
    assert target.path == app_root / "modules" / "billing" / "migrations"


def test_resolve_target_unknown_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_caps(monkeypatch, [], {})
    with pytest.raises(MigrationDiscoveryError, match="no migration package labeled"):
        resolve_migration_target("nope")


def test_empty_versions_dir_is_not_runnable_but_is_discoverable(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # audit ships a real revision; eventbus's versions/ exists but holds no revision.
    audit_dir = _make_tree_dir(tmp_path / "caps" / "audit", with_versions=True)
    eventbus_dir = _make_tree_dir(
        tmp_path / "caps" / "eventbus", with_versions=True, with_revision=False
    )
    _patch_caps(
        monkeypatch,
        [
            _FakeEntryPoint("audit", "terp.capabilities.audit"),
            _FakeEntryPoint("eventbus", "terp.capabilities.eventbus"),
        ],
        {
            "terp.capabilities.audit": audit_dir,
            "terp.capabilities.eventbus": eventbus_dir,
        },
    )

    # An empty versions/ is *initialised* but not *runnable*: excluded from the runnable
    # set (so it can never be upgraded or reported "current"), yet still discoverable so
    # its models can be imported for a sibling's first-revision foreign key.
    assert [tree.label for tree in resolve_migration_trees()] == ["audit"]
    all_trees = resolve_all_migration_trees()
    assert [tree.label for tree in all_trees] == ["audit", "eventbus"]

    eventbus = next(tree for tree in all_trees if tree.label == "eventbus")
    assert eventbus.has_revisions is True  # the versions/ directory exists (initialised)
    assert eventbus.has_revision_files is False  # but holds no revision (not runnable)


def test_resolve_all_includes_app_module_without_revisions(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_caps(monkeypatch, [], {})
    app_root = tmp_path / "app"
    # alpha has a module directory but no migrations at all; beta ships a real revision.
    (app_root / "modules" / "alpha").mkdir(parents=True)
    _make_tree_dir(app_root / "modules" / "beta", with_versions=True)

    runnable = [tree.label for tree in resolve_migration_trees(app_root, package="app")]
    discovered = [
        tree.label for tree in resolve_all_migration_trees(app_root, package="app")
    ]

    assert runnable == ["beta"]  # alpha is not runnable (it authored no revision)
    assert discovered == ["alpha", "beta"]  # but alpha is still discoverable for imports
