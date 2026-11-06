"""The runtime security cases are well-formed, and every one has evidence named in the index.

The cases (``tests/runtime_security/runtime-security.fixtures.json``) are requirements this
framework proves by running them (``tests/runtime_security/README.md``).
``docs/security-boundaries.md`` is the index of that evidence, and this holds it to the cases in
both directions: every case has a row, every case a row names is one the fixtures have, and every
test file and test function a row names exists. Without it the index is prose: a case added, or a
test renamed under a row, would leave it claiming evidence nobody runs.

The cases live beside the tests that run them (ADR 0203), so a case, its row and its tests land
in one change, and nothing here waits for another repository's release.
"""

from __future__ import annotations

import ast
import copy
import json
import re

import pytest

from terp.arch.deployment._jsonschema import check_schema, validate
from tests.architecture.rule_layout import REPO_ROOT, RUNTIME_SECURITY, catalog_dir

_INDEX = REPO_ROOT / "docs" / "security-boundaries.md"
_FIXTURES = RUNTIME_SECURITY / "runtime-security.fixtures.json"
_SCHEMA = RUNTIME_SECURITY / "runtime-security.schema.json"

_CASE = re.compile(r"`([a-z][a-z0-9-]*\.[a-z][a-z0-9-]*)`")
_EVIDENCE = re.compile(r"`([^`]+)`")

Row = tuple[list[str], list[str]]


def _artifacts() -> tuple[dict, dict]:
    return (
        json.loads(_FIXTURES.read_text(encoding="utf-8")),
        json.loads(_SCHEMA.read_text(encoding="utf-8")),
    )


def _problems_of(instance: object, schema: dict) -> list[str]:
    return [f"{problem.path or '<document>'}: {problem.detail}" for problem in validate(instance, schema)]


def _cases() -> set[str]:
    fixtures, _ = _artifacts()
    return {case["id"] for case in fixtures["cases"]}


# --------------------------------------------------------------------------- #
# the cases themselves
# --------------------------------------------------------------------------- #
def test_the_cases_validate_and_name_real_catalog_rules() -> None:
    fixtures, schema = _artifacts()
    check_schema(schema)
    assert _problems_of(fixtures, schema) == []
    ids = [case["id"] for case in fixtures["cases"]]
    assert len(ids) == len(set(ids)), "a repeated id makes evidence ambiguous"
    for case in fixtures["cases"]:
        for rule in case["rules"]:
            surface, _, name = rule.partition("/")
            assert (catalog_dir(surface) / f"{name}.json").is_file(), (
                f"{case['id']}: names {rule!r}, which no catalog entry declares"
            )


@pytest.mark.parametrize("field", ["setup", "exercise", "expected", "controls"])
def test_a_case_without_actions_outcomes_or_controls_is_not_a_requirement(field: str) -> None:
    fixtures, schema = _artifacts()
    invalid = copy.deepcopy(fixtures)
    invalid["cases"][0][field] = []
    assert _problems_of(invalid, schema)
    del invalid["cases"][0][field]
    assert _problems_of(invalid, schema)


@pytest.mark.parametrize("field", ["id", "capability"])
def test_case_identifiers_cannot_end_in_a_newline(field: str) -> None:
    fixtures, schema = _artifacts()
    invalid = copy.deepcopy(fixtures)
    invalid["cases"][0][field] += "\n"
    assert _problems_of(invalid, schema)


def test_an_empty_or_wrong_version_document_is_refused() -> None:
    fixtures, schema = _artifacts()
    assert _problems_of(fixtures | {"cases": []}, schema)
    assert _problems_of(fixtures | {"runtime_security": True}, schema)
    assert _problems_of(fixtures | {"runtime_security": 2}, schema)


def test_the_cases_cover_the_security_boundaries_they_claim() -> None:
    # These stable identifiers are the minimum, not a count a newly added case can preserve
    # while accidentally removing another boundary.
    assert _cases() >= {
        "scope.relationships", "writes.denial", "tokens.snapshot",
        "oidc.browser-binding", "sessions.logout", "outbox.finalize",
        "egress.budgets", "logs.redaction", "config.transport",
        "webhooks.envelope", "jobs.atomicity", "files.binding",
        "permissions.floor-and-grant", "replay.current-authority",
        "streams.current-grants", "leases.protected-effects",
        "sessions.rotation", "native.browser-refused",
        "accounts.enumeration", "accounts.proof-of-address", "accounts.single-use",
        "accounts.sealed-tokens", "accounts.expiry", "accounts.backoff",
        "accounts.lowest-rank", "accounts.close",
    }


# --------------------------------------------------------------------------- #
# the evidence index
# --------------------------------------------------------------------------- #
def _rows(text: str) -> list[Row]:
    """The index's rows as (case ids, evidence references), below its header row."""
    rows: list[Row] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Case", "---"):
            continue
        rows.append((_CASE.findall(cells[0]), _EVIDENCE.findall(cells[2])))
    return rows


def _problems(rows: list[Row], cases: set[str]) -> list[str]:
    """What is wrong with *rows* as the index of *cases*."""
    cited = {case for named, _ in rows for case in named}
    problems = [f"a row names no case: {evidence}" for named, evidence in rows if not named]
    problems += [f"the row for {named} names no evidence" for named, evidence in rows if not evidence]
    if missing := sorted(cases - cited):
        problems.append(
            f"the index has no row for these cases: {missing}. Add a row naming each case and "
            "the tests that run it, or the reason it is not applicable here."
        )
    if unknown := sorted(cited - cases):
        problems.append(
            f"the index names cases the fixtures do not have: {unknown}. Fix the id, or add the "
            "case to tests/runtime_security/runtime-security.fixtures.json in the same change."
        )
    return problems


def test_the_index_is_held_to_the_cases() -> None:
    rows = _rows(_INDEX.read_text(encoding="utf-8"))
    assert len(rows) >= len(_cases()), "the index lost its table, or its table its rows"
    assert _problems(rows, _cases()) == []


def test_every_piece_of_evidence_a_row_names_exists() -> None:
    missing: list[str] = []
    for _, evidence in _rows(_INDEX.read_text(encoding="utf-8")):
        for reference in evidence:
            path, _, function = reference.partition("::")
            source = REPO_ROOT / path
            if not source.is_file():
                missing.append(reference)
            elif function:
                tree = ast.parse(source.read_text(encoding="utf-8"))
                if function not in {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}:
                    missing.append(reference)
    assert not missing, f"docs/security-boundaries.md names evidence that does not exist: {missing}"


_TABLE = "| Case | Runtime scenario | Regression evidence |\n|---|---|---|\n"


@pytest.mark.parametrize(
    ("table", "cases", "refusal"),
    [
        ("| `a.one` | x | `t.py` |", {"a.one", "a.two"}, "no row for these cases: ['a.two']"),
        ("| `a.one`, `a.typo` | x | `t.py` |", {"a.one"}, "names cases the fixtures do not have"),
        ("| not a case | x | `t.py` |", set(), "a row names no case"),
        ("| `a.one` | x | none |", {"a.one"}, "names no evidence"),
    ],
)
def test_each_way_the_index_can_be_wrong_is_refused(table: str, cases: set[str], refusal: str) -> None:
    problems = _problems(_rows(_TABLE + table), cases)
    assert any(refusal in problem for problem in problems), problems


def test_a_case_shared_by_two_rows_is_accepted() -> None:
    """The control: a sound index, with a case two rows share, has no problem."""
    table = "| `a.one` | x | `t.py` |\n| `a.one`, `a.two` | y | `u.py::test_y` |"
    assert _problems(_rows(_TABLE + table), {"a.one", "a.two"}) == []
