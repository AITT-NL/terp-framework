"""Phase 5 CLI scaffolding: ``terp new module``, ``terp api-docs``, ``terp check``.

Verifies the agent-facing authoring tools: a scaffolded module is *canonical* (passes
every architecture rule but the migration step, which `terp migrate make` completes),
the generated API contract reflects the live kernel, and `terp check` runs the gate.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.arch import check_app  # noqa: E402
from terp.cli import api_docs, main, new_module  # noqa: E402
from terp.cli.apidocs import _kind, _summary  # noqa: E402
from terp.cli.scaffold import _model_name, _singular, new_module_message  # noqa: E402

_SLOTS = {"__init__.py", "models.py", "schemas.py", "service.py", "router.py", "module.py"}


def test_singularize_and_model_name() -> None:
    assert _singular("invoices") == "invoice"
    assert _singular("billing") == "billing"
    assert _model_name("invoices") == "Invoice"
    assert _model_name("billing") == "Billing"


def test_new_module_writes_the_five_slots(tmp_path: pathlib.Path) -> None:
    paths = new_module("invoices", root=tmp_path)
    assert {p.name for p in paths} == _SLOTS
    module = tmp_path / "app" / "modules" / "invoices"
    assert (module / "models.py").read_text().count("class Invoice(BaseTable") == 1
    assert "ModuleSpec" in (module / "module.py").read_text()


def test_new_module_emits_frontend_when_app_present(tmp_path: pathlib.Path) -> None:
    # A frontend app is detected by frontend/src/modules; the module then spans both stacks.
    (tmp_path / "frontend" / "src" / "modules").mkdir(parents=True)
    paths = new_module("invoices", root=tmp_path)
    assert {p.name for p in paths} == _SLOTS | {"module.tsx", "InvoicesList.tsx"}
    frontend = tmp_path / "frontend" / "src" / "modules" / "invoices"
    assert "defineModuleManifest" in (frontend / "module.tsx").read_text()
    assert 'name: "invoices"' in (frontend / "module.tsx").read_text()
    view = (frontend / "InvoicesList.tsx").read_text()
    assert "export function InvoicesList" in view
    # The starter view composes the shared ResourceList + useResource primitives (the blessed
    # pattern, so a scaffolded module matches the reference example) ...
    assert "ResourceList" in view
    assert "useResource" in view
    # ... framed by a page archetype (buildAppRouter refuses a routed view without one) ...
    assert "OverviewPage" in view
    # ... and documents the typed-client pattern for the app's own endpoints.
    assert "useTerpClient<paths>()" in view


def test_new_module_skips_frontend_without_app(tmp_path: pathlib.Path) -> None:
    paths = new_module("invoices", root=tmp_path)
    assert {p.name for p in paths} == _SLOTS
    assert not any(p.suffix == ".tsx" for p in paths)


def test_new_module_no_frontend_flag_skips_frontend(tmp_path: pathlib.Path) -> None:
    (tmp_path / "frontend" / "src" / "modules").mkdir(parents=True)
    paths = new_module("invoices", root=tmp_path, frontend=False)
    assert not any(p.suffix == ".tsx" for p in paths)


def test_new_module_message_mentions_openapi_when_frontend(tmp_path: pathlib.Path) -> None:
    (tmp_path / "frontend" / "src" / "modules").mkdir(parents=True)
    paths = new_module("invoices", root=tmp_path)
    message = new_module_message("invoices", paths)
    assert "terp openapi" in message
    # Both halves of the codegen pipeline: exporting the contract alone leaves
    # the typed client stale — the npm generate step must be taught too.
    assert "npm --prefix frontend run generate" in message
    assert "/api/v1/invoices/" in message


def test_new_module_refuses_existing_frontend_module(tmp_path: pathlib.Path) -> None:
    (tmp_path / "frontend" / "src" / "modules" / "invoices").mkdir(parents=True)
    with pytest.raises(SystemExit):
        new_module("invoices", root=tmp_path)


def test_scaffold_passes_every_rule_but_migrations(tmp_path: pathlib.Path) -> None:
    new_module("invoices", root=tmp_path)
    violations = check_app(tmp_path, package="app")
    # The only outstanding item is the first migration (run `terp migrate make`).
    assert {v.rule for v in violations} <= {"tables_have_migrations"}


def test_scaffold_modules_import_and_build_an_app(tmp_path: pathlib.Path) -> None:
    # The scaffold is runnable, not just lint-clean: every slot imports and the
    # ModuleSpec mounts under create_app (catches a stray expression in a template).
    # A unique package avoids clashing with the example app's `app` on sys.path.
    new_module("invoices", root=tmp_path, package="genapp")
    sys.path.insert(0, str(tmp_path))
    try:
        for slot in ("models", "schemas", "service", "router", "module"):
            importlib.import_module(f"genapp.modules.invoices.{slot}")
        from terp.core import create_app

        spec = importlib.import_module("genapp.modules.invoices.module").module
        assert create_app([spec]) is not None
    finally:
        sys.path.remove(str(tmp_path))
        for name in [m for m in sys.modules if m.startswith("genapp")]:
            del sys.modules[name]


def test_new_module_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    new_module("invoices", root=tmp_path)
    with pytest.raises(SystemExit):
        new_module("invoices", root=tmp_path)


def test_new_module_rejects_bad_name(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit):
        new_module("1bad", root=tmp_path)
    with pytest.raises(SystemExit):
        new_module("class", root=tmp_path)


def test_new_module_message_lists_next_steps() -> None:
    msg = new_module_message("invoices", [pathlib.Path("a"), pathlib.Path("b")])
    assert "terp migrate make invoices" in msg
    assert "2 files" in msg


def test_cli_new_module_prints_summary(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["new", "module", "billing", "--root", str(tmp_path)])
    assert (tmp_path / "app" / "modules" / "billing" / "service.py").exists()
    assert "Scaffolded module 'billing'" in capsys.readouterr().out


def test_api_docs_generate_contract(tmp_path: pathlib.Path) -> None:
    paths = api_docs(tmp_path)
    md = (tmp_path / "platform-api.md").read_text()
    pyi = (tmp_path / "terp_core.pyi").read_text()
    assert {p.name for p in paths} == {"platform-api.md", "terp_core.pyi"}
    assert "class BaseService: ..." in pyi
    assert "def create_app" in pyi
    # The stub carries the *real* signature, not a content-free `(*args, **kwargs)`.
    assert "(*args: Any, **kwargs: Any)" not in pyi
    assert "def create_app(" in pyi
    assert "BaseService" in md
    # The stub must be valid Python (parseable) — a real type-checkable contract.
    ast.parse(pyi)


def test_apidocs_kind_and_summary() -> None:
    assert _kind(int) == "class"
    assert _kind(api_docs) == "function"
    assert _kind(7) == "value"
    assert _summary(lambda: None) == ""  # no docstring -> empty headline


def test_cli_api_docs_writes_files(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["api-docs", "--out", str(tmp_path)])
    assert "wrote" in capsys.readouterr().out


def test_cli_check_passes_on_the_example_app(capsys: pytest.CaptureFixture[str]) -> None:
    example = _REPO_ROOT / "apps" / "example"
    main(["check", "--root", str(example), "--budget", str(example / "escape-hatch-budget.json")])
    assert "clean" in capsys.readouterr().out
