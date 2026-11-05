"""Every runtime security case the pinned Terp Standard packages has evidence named in the index.

The standard's runtime security cases (``runtime-security.fixtures.json``) are requirements an
implementation proves by running them, and its README asks the evidence to name each applicable
case and a runnable test. ``docs/security-boundaries.md`` is that index for the reference
implementation, and this holds it to the cases the PINNED release packages: every case has a row,
every case a row names is one the standard has, and every test file and test function a row names
exists. Without it the index is prose: a case added to the standard, or a test renamed under a
row, would leave it claiming evidence nobody runs.

The evidence may run ahead of the pinned release, as the deployment schema's mirror may
(``SPEC_RELEASE``): a case the next release adds is written, and its evidence built, before that
release is published. Such a case is allowed only inside the declared window below, which names
the release that is to carry it. When the pin reaches that release the window must be empty,
because the package then answers for every id in it, and an id it does not carry is a typo or a
case that changed its name.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
from collections.abc import Iterable

import pytest
import terp_spec

from terp.arch import SPEC_VERSION

_REPO = pathlib.Path(__file__).resolve().parents[2]
_INDEX = _REPO / "docs" / "security-boundaries.md"

#: The cases the evidence runs ahead of the pinned standard, and the release that is to carry them.
_AHEAD_RELEASE = "0.43.0"
_AHEAD = frozenset(
    {
        "sessions.rotation",
        "native.browser-refused",
        "accounts.enumeration",
        "accounts.proof-of-address",
        "accounts.single-use",
        "accounts.sealed-tokens",
        "accounts.expiry",
        "accounts.backoff",
        "accounts.lowest-rank",
        "accounts.close",
    }
)

_CASE = re.compile(r"`([a-z][a-z0-9-]*\.[a-z][a-z0-9-]*)`")
_EVIDENCE = re.compile(r"`([^`]+)`")

Row = tuple[list[str], list[str]]


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _packaged() -> set[str]:
    fixtures = json.loads((terp_spec.spec_dir() / "runtime-security.fixtures.json").read_text(encoding="utf-8"))
    return {case["id"] for case in fixtures["cases"]}


def _rows(text: str) -> list[Row]:
    """The index's rows as (case ids, evidence references), below its header row."""
    rows: list[Row] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Case", "---"):
            continue
        rows.append((_CASE.findall(cells[0]), _EVIDENCE.findall(cells[2])))
    return rows


def _problems(rows: list[Row], packaged: set[str], ahead: Iterable[str], release: str, pin: str) -> list[str]:
    """What is wrong with *rows* as the index of the cases *packaged* by terp-spec *pin*."""
    ahead = frozenset(ahead)
    cited = {case for cases, _ in rows for case in cases}
    problems = [f"a row names no case: {evidence}" for cases, evidence in rows if not cases]
    problems += [f"the row for {cases} names no evidence" for cases, evidence in rows if not evidence]
    if missing := sorted(packaged - cited):
        problems.append(
            f"terp-spec {pin} packages cases the index has no row for: {missing}. Add a row naming "
            "each case and the tests that run it, or the reason it is not applicable here."
        )
    if unknown := sorted(cited - packaged - ahead):
        problems.append(
            f"the index names cases terp-spec {pin} does not package and the window does not "
            f"declare: {unknown}. Fix the id, or declare it in _AHEAD with the release to carry it."
        )
    if unwritten := sorted(ahead - cited):
        problems.append(f"cases declared ahead of the pin have no row: {unwritten}")
    if arrived := sorted(ahead & packaged):
        problems.append(f"terp-spec {pin} now packages {arrived}: drop them from _AHEAD")
    if ahead and _version(release) <= _version(pin):
        problems.append(
            f"the pin is terp-spec {pin}, and the window still declares cases for {release}: "
            "the package answers for them now, so empty _AHEAD"
        )
    return problems


def test_the_index_is_held_to_the_cases_the_pinned_standard_packages() -> None:
    rows = _rows(_INDEX.read_text(encoding="utf-8"))
    assert len(rows) >= len(_packaged()), "the index lost its table, or its table its rows"
    assert _problems(rows, _packaged(), _AHEAD, _AHEAD_RELEASE, SPEC_VERSION) == []


def test_every_piece_of_evidence_a_row_names_exists() -> None:
    missing: list[str] = []
    for _, evidence in _rows(_INDEX.read_text(encoding="utf-8")):
        for reference in evidence:
            path, _, function = reference.partition("::")
            source = _REPO / path
            if not source.is_file():
                missing.append(reference)
            elif function:
                tree = ast.parse(source.read_text(encoding="utf-8"))
                if function not in {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}:
                    missing.append(reference)
    assert not missing, f"docs/security-boundaries.md names evidence that does not exist: {missing}"


_TABLE = "| Case | Runtime scenario | Regression evidence |\n|---|---|---|\n"


@pytest.mark.parametrize(
    ("table", "packaged", "ahead", "release", "pin", "refusal"),
    [
        ("| `a.one` | x | `t.py` |", {"a.one", "a.two"}, (), "0.2.0", "0.1.0", "no row for: ['a.two']"),
        ("| `a.one`, `a.typo` | x | `t.py` |", {"a.one"}, (), "0.2.0", "0.1.0", "does not package and the window"),
        ("| `a.one` | x | `t.py` |", {"a.one"}, ("a.next",), "0.2.0", "0.1.0", "declared ahead of the pin have no row"),
        ("| `a.one` | x | `t.py` |", {"a.one"}, ("a.one",), "0.2.0", "0.1.0", "now packages ['a.one']"),
        ("| `a.one`, `a.next` | x | `t.py` |", {"a.one"}, ("a.next",), "0.2.0", "0.2.0", "so empty _AHEAD"),
        ("| not a case | x | `t.py` |", set(), (), "0.2.0", "0.1.0", "a row names no case"),
        ("| `a.one` | x | none |", {"a.one"}, (), "0.2.0", "0.1.0", "names no evidence"),
    ],
)
def test_each_way_the_index_can_be_wrong_is_refused(
    table: str, packaged: set[str], ahead: tuple[str, ...], release: str, pin: str, refusal: str
) -> None:
    problems = _problems(_rows(_TABLE + table), packaged, ahead, release, pin)
    assert any(refusal in problem for problem in problems), problems


def test_a_case_cited_ahead_and_a_case_shared_by_rows_are_both_accepted() -> None:
    """The control: a sound index, with a window and a case two rows share, has no problem."""
    table = "| `a.one` | x | `t.py` |\n| `a.one`, `a.next` | y | `u.py::test_y` |"
    assert _problems(_rows(_TABLE + table), {"a.one"}, ("a.next",), "0.2.0", "0.1.0") == []
