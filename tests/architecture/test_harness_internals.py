"""Coverage gate: the harness's own helper + fail-closed error paths.

The harness is Terp's enforcement product, so its internal helpers and error
branches are themselves under test — a gap here is a blind spot in the gate.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from terp.arch import check_app, check_escape_hatch_budget
from terp.arch._ast import _SECURITY_SKIP_DIRS, base_name, iter_python_files
from terp.arch.rules import (
    assert_app_clean,
    check_input_str_fields_have_max_length,
    check_modules_declare_policy,
    check_routes_declare_response_model,
)
from terp.arch.rules._support import (
    _annotation_type_name,
    _has_max_length,
    _is_dml_expression,
    _is_text_dml,
    _module_parts,
    _module_under,
    _rel,
    _resolve_relative_import,
    _service_model,
)
from terp.arch.rules.http import _is_no_body_status


def _expr(source: str) -> ast.expr:
    return ast.parse(source, mode="eval").body


def _write(app_root: pathlib.Path, rel: str, source: str) -> None:
    path = app_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _rule_names(violations: list) -> set[str]:
    return {violation.rule for violation in violations}


# --------------------------------------------------------------------------- #
# _ast helpers
# --------------------------------------------------------------------------- #
def test_base_name_unwraps_every_expression_form() -> None:
    assert base_name(_expr("Widget")) == "Widget"
    assert base_name(_expr("pkg.mod.Widget")) == "Widget"
    assert base_name(_expr("BaseService[Widget]")) == "BaseService"
    assert base_name(_expr("Factory()")) == "Factory"
    assert base_name(_expr("1 + 2")) is None


def test_iter_python_files_skips_non_application_dirs(tmp_path: pathlib.Path) -> None:
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "ok.py").write_text("x = 1", encoding="utf-8")
    for skip in ("tests", "__pycache__", "migrations"):
        (tmp_path / skip).mkdir()
        (tmp_path / skip / "skip.py").write_text("x = 1", encoding="utf-8")
    assert {path.name for path in iter_python_files(tmp_path)} == {"ok.py"}
    # The security skip set keeps tests/ and migrations/ in scope (importable code).
    assert {path.name for path in iter_python_files(tmp_path, skip_dirs=_SECURITY_SKIP_DIRS)} == {
        "ok.py",
        "skip.py",
    }


# --------------------------------------------------------------------------- #
# rules helpers — defensive branches
# --------------------------------------------------------------------------- #
def test_rel_falls_back_when_path_is_unrelated(tmp_path: pathlib.Path) -> None:
    unrelated = pathlib.Path(__file__).resolve()
    assert _rel(unrelated, tmp_path / "app") == str(unrelated)


def test_module_under_handles_edge_cases() -> None:
    assert _module_under(pathlib.Path("app/services/x.py"), "app") is None
    assert _module_under(pathlib.Path("app/modules"), "app") is None
    assert _module_under(pathlib.Path("app/modules/notes/x.py"), "app") == "notes"


def test_has_max_length_false_for_non_field_value() -> None:
    assert _has_max_length(_expr("str")) is False
    assert _has_max_length(_expr("Field(default='x')")) is False
    assert _has_max_length(_expr("Field(max_length=10)")) is True


def test_service_model_none_without_model_assignment() -> None:
    node = ast.parse("class S:\n    other = 1\n").body[0]
    assert isinstance(node, ast.ClassDef)
    assert _service_model(node) is None


def test_module_parts_drops_init_and_keeps_package_prefix(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    service = app / "modules" / "notes" / "service.py"
    assert _module_parts(service, app) == ["app", "modules", "notes", "service"]
    init = app / "modules" / "notes" / "__init__.py"
    assert _module_parts(init, app) == ["app", "modules", "notes"]


def test_module_parts_falls_back_when_path_is_unrelated(tmp_path: pathlib.Path) -> None:
    # A path outside the app root hits the ValueError fallback (returns raw parts).
    unrelated = pathlib.Path(__file__).resolve()
    assert _module_parts(unrelated, tmp_path / "app")


def test_resolve_relative_import_resolves_and_clamps() -> None:
    parts = ["app", "modules", "notes", "service"]
    assert _resolve_relative_import(parts, 1, "models") == "app.modules.notes.models"
    assert _resolve_relative_import(parts, 2, "tasks.service") == "app.modules.tasks.service"
    assert _resolve_relative_import(parts, 1, None) == "app.modules.notes"
    # A level deeper than the package nesting clamps the base to empty.
    assert _resolve_relative_import(parts, 9, "x") == "x"


def test_is_dml_expression_distinguishes_text_reads_from_writes() -> None:
    assert _is_dml_expression(_expr("update(Note).values(title='x')")) is True
    assert _is_dml_expression(_expr("text('UPDATE notes SET title=:t')")) is True
    assert _is_dml_expression(_expr("text('SELECT 1')")) is False
    # Dynamic SQL through text(...) is unknowable statically, so it fails closed.
    assert _is_dml_expression(_expr("text(sql)")) is True
    assert _is_text_dml(_expr("select(Note)")) is False


def test_annotation_type_name_unwraps_wrappers() -> None:
    assert _annotation_type_name(_expr("LoginRequest")) == "LoginRequest"
    assert _annotation_type_name(_expr("schemas.LoginRequest")) == "LoginRequest"
    assert _annotation_type_name(_expr("Annotated[LoginRequest, Body()]")) == "LoginRequest"
    assert _annotation_type_name(_expr("Optional[LoginRequest]")) == "LoginRequest"
    assert _annotation_type_name(_expr("LoginRequest | None")) == "LoginRequest"
    assert _annotation_type_name(_expr("None | LoginRequest")) == "LoginRequest"
    # A non-Annotated/Optional subscript resolves to its head; a missing annotation
    # is None.
    assert _annotation_type_name(_expr("Page[Widget]")) == "Page"
    assert _annotation_type_name(None) is None


def test_is_no_body_status_recognizes_codes_and_names() -> None:
    assert _is_no_body_status(_expr("204")) is True
    assert _is_no_body_status(_expr("200")) is False
    assert _is_no_body_status(_expr("status.HTTP_204_NO_CONTENT")) is True
    assert _is_no_body_status(_expr("HTTPStatus.NO_CONTENT")) is True
    assert _is_no_body_status(_expr("NO_CONTENT")) is True
    assert _is_no_body_status(_expr("compute_status()")) is False


def test_input_rule_ignores_non_str_subscript_annotation(tmp_path: pathlib.Path) -> None:
    # A container with no str element (``list[int]``) and a ``dict`` (whose size is
    # not the right thing for max_length to bound) both need no cap; only a
    # str-bearing sequence does (covered in the harness's positive test).
    app = tmp_path / "app"
    _write(
        app,
        "modules/x/schemas.py",
        "class XCreate(BaseSchema):\n    counts: list[int] = []\n    labels: dict[str, int] = {}\n",
    )
    assert check_input_str_fields_have_max_length(app) == []


def test_routes_rule_ignores_non_http_decorators(tmp_path: pathlib.Path) -> None:
    # A non-Call decorator and a non-HTTP Call decorator are both skipped.
    app = tmp_path / "app"
    _write(
        app,
        "modules/x/router.py",
        "@staticmethod\n@functools.lru_cache()\ndef helper() -> None:\n    return None\n",
    )
    assert check_routes_declare_response_model(app) == []


def test_modules_declare_policy_flags_a_file_with_no_modulespec(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(app, "modules/orphan/module.py", "value = 1  # no ModuleSpec at all\n")
    assert _rule_names(check_modules_declare_policy(app)) == {"modules_declare_policy"}


def test_assert_app_clean_lists_each_violation(tmp_path: pathlib.Path) -> None:
    # A module.py whose ModuleSpec omits policy= produces a violation that
    # assert_app_clean stringifies into its message (exercises ArchViolation.__str__).
    app = tmp_path / "app"
    _write(
        app,
        "modules/billing/module.py",
        "module = ModuleSpec(name='billing', router=router)\n",
    )
    with pytest.raises(AssertionError, match=r"architecture violation") as excinfo:
        assert_app_clean(app)
    assert "modules_declare_policy" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# orchestrator + budget fail-closed paths
# --------------------------------------------------------------------------- #
def test_check_app_rejects_a_missing_directory(tmp_path: pathlib.Path) -> None:
    with pytest.raises(NotADirectoryError):
        check_app(tmp_path / "does-not-exist")


def _budget(tmp_path: pathlib.Path, content: str) -> pathlib.Path:
    app = tmp_path / "app"
    (app / "modules").mkdir(parents=True, exist_ok=True)
    budget = tmp_path / "budget.json"
    budget.write_text(content, encoding="utf-8")
    return app


def test_budget_rejects_missing_file(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    (app / "modules").mkdir(parents=True)
    violations = check_escape_hatch_budget(app, budget_path=tmp_path / "nope.json")
    assert {v.rule for v in violations} == {"escape_hatch_budget"}
    assert "not found" in violations[0].message


def test_budget_rejects_invalid_json(tmp_path: pathlib.Path) -> None:
    app = _budget(tmp_path, "{ not json")
    violations = check_escape_hatch_budget(app, budget_path=tmp_path / "budget.json")
    assert "not valid JSON" in violations[0].message


def test_budget_rejects_non_object_and_non_int_counts(tmp_path: pathlib.Path) -> None:
    app = _budget(tmp_path, '["a"]')
    assert "JSON object" in check_escape_hatch_budget(
        app, budget_path=tmp_path / "budget.json"
    )[0].message

    app = _budget(tmp_path, '{"arch-allow-no-internal-imports": "1"}')
    assert "JSON object" in check_escape_hatch_budget(
        app, budget_path=tmp_path / "budget.json"
    )[0].message
