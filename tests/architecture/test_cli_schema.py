"""``terp inspect schema`` — the Schema Graph (ownership / traits / fail-visible alarms).

Proves the "never skip a model" contract: every mapped table is attributed to its
owning migration tree, kernel traits are reported, and anything the framework
cannot account for — an unowned model, a non-BaseTable app model, a raw Table,
or a ``table=True`` class that never reached the metadata — is alarmed, never
silently dropped. The example app is the canonical all-green fixture.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main
from terp.cli.schema import (
    build_schema_graph,
    render_schema_graph,
    scan_declared_table_models,
)
from terp.core.migrations import MigrationTree

_EXAMPLE = _REPO_ROOT / "apps" / "example"


def _example_graph() -> dict:
    """Run the real CLI in a SUBPROCESS: importing every installed capability's
    models pollutes the process-global SQLModel metadata (later tests create_all
    over it), so the example graph is built out of process, like the Studio does."""
    script = (
        "import sys; sys.path.insert(0, r'" + str(_EXAMPLE) + "'); "
        "from terp.cli import main; "
        "main(['inspect', 'schema', '--app-root', r'" + str(_EXAMPLE) + "', "
        "'--format', 'json'])"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_schema_graph_covers_every_example_model_with_zero_alarms() -> None:
    # The completeness guard: all four app modules AND the installed capability
    # tables are attributed, and no alarm channel fires on the canonical app.
    graph = _example_graph()
    assert set(graph) == {
        "tables",
        "unowned_tables",
        "non_canonical_models",
        "unmapped_tables",
        "unimported_models",
    }
    by_name = {table["name"]: table for table in graph["tables"]}
    assert {"note", "task", "project", "journal"} <= set(by_name)
    assert {"identity_user", "access_grant", "audit_event", "user_group"} <= set(by_name)
    assert graph["unowned_tables"] == []
    assert graph["non_canonical_models"] == []
    assert graph["unmapped_tables"] == []
    assert graph["unimported_models"] == []
    # Ownership + kind attribution and the enforced kernel traits are reported.
    assert (by_name["journal"]["module"], by_name["journal"]["kind"]) == ("journals", "app")
    assert by_name["journal"]["traits"]["owned"] is True
    assert by_name["project"]["traits"]["tenant_scoped"] is True
    assert by_name["task"]["traits"]["soft_delete"] is True
    assert by_name["identity_user"]["kind"] == "capability"
    # A capability's governed non-BaseTable primitive stays visible as a trait...
    assert by_name["audit_event"]["traits"]["base_table"] is False
    # ...without polluting the app's alarm channel (its budget governs it).


def test_cli_inspect_schema_prints_the_graph(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    # In-process dispatch coverage WITHOUT touching the global registry: trees
    # resolve to nothing, and the source scan still alarms a planted stray model.
    import terp.cli as cli_mod

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "stash.py").write_text(
        "class Hidden(SQLModel, table=True):\n    pass\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli_mod, "import_declared_models", lambda *a, **k: [])
    monkeypatch.setattr(
        cli_mod,
        "build_schema_graph",
        lambda trees, source_models: build_schema_graph(
            trees, mappers=[], metadata_tables=[], source_models=source_models
        ),
    )
    main(["inspect", "schema", "--app-root", str(tmp_path), "--format", "json"])
    graph = json.loads(capsys.readouterr().out)
    assert graph["tables"] == []
    (unimported,) = graph["unimported_models"]
    assert unimported["model"] == "Hidden"


class _FakeColumn:
    def __init__(self, name: str, *, primary_key: bool = False) -> None:
        self.name = name
        self.type = "UUID"
        self.nullable = False
        self.primary_key = primary_key
        self.unique = False


class _FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.schema = None
        self.columns = [_FakeColumn("id", primary_key=True)]
        self.foreign_keys: list = []


def _mapper(table: _FakeTable, model: type) -> types.SimpleNamespace:
    return types.SimpleNamespace(local_table=table, class_=model)


_TREES = (
    MigrationTree(label="notes", import_path="app.modules.notes", path=pathlib.Path(".")),
    MigrationTree(
        label="audit", import_path="terp.capabilities.audit", path=pathlib.Path(".")
    ),
)


def _model(name: str, module: str, bases: tuple[type, ...] = ()) -> type:
    model = type(name, bases, {})
    model.__module__ = module
    return model


def test_schema_graph_alarms_every_unaccountable_shape() -> None:
    from terp.core import BaseTable

    owned_model = _model("Note", "app.modules.notes.models", (BaseTable,))
    stray_model = _model("Stray", "app.helpers.stash")  # no tree owns it, no BaseTable
    cap_primitive = _model("AuditEvent", "terp.capabilities.audit.models")  # governed
    graph = build_schema_graph(
        _TREES,
        mappers=[
            _mapper(_FakeTable("note"), owned_model),
            _mapper(_FakeTable("stray"), stray_model),
            _mapper(_FakeTable("audit_event"), cap_primitive),
        ],
        metadata_tables=[_FakeTable("note"), _FakeTable("stray"), _FakeTable("hand_rolled")],
        source_models={"Ghost": ("app/modules/ghost/models.py", 7)},
    )
    assert [t["name"] for t in graph["tables"]] == ["audit_event", "note", "stray"]
    # Unowned: no migration tree reaches the stray's module — migrations skip it.
    (unowned,) = graph["unowned_tables"]
    assert (unowned["table"], unowned["model_module"]) == ("stray", "app.helpers.stash")
    # Non-canonical: the app-side stray lacks BaseTable; the capability's governed
    # primitive does NOT alarm (its trait stays visible on the table entry).
    (non_canonical,) = graph["non_canonical_models"]
    assert non_canonical["table"] == "stray"
    audit = next(t for t in graph["tables"] if t["name"] == "audit_event")
    assert audit["traits"]["base_table"] is False
    # Raw Table with no mapped model: reported, never dropped.
    (unmapped,) = graph["unmapped_tables"]
    assert unmapped["table"] == "hand_rolled"
    # Declared in source but never imported: the "skipped model" alarm.
    (unimported,) = graph["unimported_models"]
    assert (unimported["model"], unimported["line"]) == ("Ghost", 7)
    # The text rendering surfaces every alarm channel.
    text = render_schema_graph(graph, fmt="text")
    for marker in ("UNOWNED", "NON-CANONICAL", "UNMAPPED", "UNIMPORTED"):
        assert marker in text


def test_scan_finds_table_models_anywhere_in_the_tree(tmp_path: pathlib.Path) -> None:
    # The AST ground truth sees a model even in a non-canonical location; the
    # keyword must be a literal table=True (table=False and plain classes skip).
    (tmp_path / "app" / "weird").mkdir(parents=True)
    (tmp_path / "app" / "weird" / "stash.py").write_text(
        "class Hidden(SQLModel, table=True):\n    pass\n"
        "class NotATable(SQLModel, table=False):\n    pass\n"
        "class Plain:\n    pass\n",
        encoding="utf-8",
    )
    # Skipped trees (tests/, caches, migrations) never contribute scan entries.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text(
        "class TestOnly(SQLModel, table=True):\n    pass\n", encoding="utf-8"
    )
    found = scan_declared_table_models(tmp_path)
    assert set(found) == {"Hidden"}
    assert found["Hidden"] == ("app/weird/stash.py", 1)


def test_import_declared_models_skips_route_only_trees_and_raises_on_real_errors(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    from terp.cli import schema as schema_mod

    # A tree whose models module does not exist is route-only: skipped, no error.
    route_only = MigrationTree(
        label="cli", import_path="terp.cli", path=tmp_path
    )  # terp.cli.models does not exist
    monkeypatch.setattr(
        schema_mod, "resolve_all_migration_trees", lambda *a, **k: [route_only]
    )
    assert schema_mod.import_declared_models(None) == [route_only]

    # A models module that itself fails to import a REAL dependency must raise —
    # a broken model file is never silently treated as route-only.
    pkg = tmp_path / "brokenpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "models.py").write_text("import missing_dep_xyz\n", encoding="utf-8")
    good = tmp_path / "goodpkg"
    good.mkdir()
    (good / "__init__.py").write_text("", encoding="utf-8")
    (good / "models.py").write_text("TABLES = ()\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        # The success path: an importable (model-less) models module loads cleanly.
        good_tree = MigrationTree(label="good", import_path="goodpkg", path=tmp_path)
        monkeypatch.setattr(
            schema_mod, "resolve_all_migration_trees", lambda *a, **k: [good_tree]
        )
        assert schema_mod.import_declared_models(None) == [good_tree]
        broken = MigrationTree(label="broken", import_path="brokenpkg", path=tmp_path)
        monkeypatch.setattr(
            schema_mod, "resolve_all_migration_trees", lambda *a, **k: [broken]
        )
        with pytest.raises(ModuleNotFoundError, match="missing_dep_xyz"):
            schema_mod.import_declared_models(None)
    finally:
        sys.path.remove(str(tmp_path))
