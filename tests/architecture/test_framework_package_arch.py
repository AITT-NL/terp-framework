"""The framework is held to the harness it ships — as far as it currently is.

`_MAX_FILE_LINES = 500` applies to every file of every consuming app. Thirty
non-test framework source files exceed it, and `core`, `arch`, `cli` and
`migrations` were not self-scanned at all — roughly 38,000 lines outside the gate
this repository sells.

Two costs, and the second is the expensive one. A consumer who hits the cap and looks
at the framework finds a 3,818-line file, so the rule reads as arbitrary rather than
principled and the first thing they ask for is an exemption. And the unscanned lines
are where a real regression would live: `capabilities` were exactly this until they
were scanned, and scanning them found the `TenantScopedService.create` /
`AccessService.grant` bypasses that `test_capability_arch` now guards.

This suite is that same pattern, pointed at the framework's own packages, in the
order they can actually be held:

* **migrations** passes the whole harness outright, with no opt-outs at all.
* **arch** passes with a checked-in budget: six oversized rule modules and one
  build-time CLI diagnostic, each carrying a justified marker. Six of those seven are
  the size cap, which is the honest shape of the finding — the largest is
  `rules/persistence.py` at 952 lines, and it is due a split by sub-theme. A budgeted
  exemption is visible, greppable and shrink-only; the silent one it replaces was none
  of those.
* **core** (72 findings) and **cli** (124, of which 98 are `no_print` — a CLI prints)
  are NOT scanned yet, and `UNSCANNED.json` records exactly what each one finds so
  the debt is counted rather than invisible.

That last part is deliberate and not a dodge. Many of those findings are inherent to
being the kernel: `no_app_instantiation` fires on `create_app`, which is the function
whose whole job is to instantiate the app. Each needs a per-finding judgement — and
some of them will be real bugs rather than exemptions, which is the point of looking.
Rubber-stamping 196 markers to turn the suite green would produce precisely the
budget-as-decoration failure the escape-hatch ratchet exists to prevent.

So the ratchet holds the line instead: a count may fall and never rise, nothing new
may join, and a package that empties leaves the record and joins the scanned list
above.
"""

from __future__ import annotations

import collections
import json
import pathlib

import pytest

from terp.arch import assert_app_clean, check_app

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "packages" / "backend"
_UNSCANNED = _BACKEND / "UNSCANNED.json"

#: package -> (source root relative to the repo, dotted package name).
_PACKAGES = {
    "core": ("core/src/terp/core", "terp.core"),
    "arch": ("arch/src/terp/arch", "terp.arch"),
    "cli": ("cli/src/terp/cli", "terp.cli"),
    "migrations": ("migrations/src/terp/migrations", "terp.migrations"),
}

#: Clean with no opt-outs at all.
_CLEAN = ("migrations",)
#: Clean with a checked-in, justified, ratcheted budget.
_BUDGETED = ("arch",)


def _root(name: str) -> pathlib.Path:
    return _BACKEND / _PACKAGES[name][0]


def _package(name: str) -> str:
    return _PACKAGES[name][1]


def _recorded() -> dict[str, dict[str, int]]:
    return json.loads(_UNSCANNED.read_text(encoding="utf-8"))["packages"]


@pytest.mark.parametrize("name", _CLEAN)
def test_clean_framework_package_passes_the_whole_harness(name: str) -> None:
    assert check_app(_root(name), package=_package(name)) == []


@pytest.mark.parametrize("name", _BUDGETED)
def test_budgeted_framework_package_passes_with_its_budget(name: str) -> None:
    budget = _BACKEND / name / "escape-hatch-budget.json"
    assert budget.is_file(), f"{name} is missing its escape-hatch budget"
    assert_app_clean(_root(name), package=_package(name), budget_path=budget)


def test_every_framework_package_is_either_scanned_or_counted() -> None:
    """No package may be silently neither. This is the guard that makes the rest a
    ratchet rather than a snapshot: a new backend package has to be scanned or
    recorded, and either way someone had to decide which."""
    accounted = set(_CLEAN) | set(_BUDGETED) | set(_recorded())
    assert set(_PACKAGES) == accounted, (
        "every framework package must be scanned here or recorded in UNSCANNED.json; "
        f"neither: {sorted(set(_PACKAGES) - accounted)}; "
        f"recorded but unknown: {sorted(accounted - set(_PACKAGES))}"
    )
    both = (set(_CLEAN) | set(_BUDGETED)) & set(_recorded())
    assert not both, f"scanned AND recorded as unscanned: {sorted(both)}"


@pytest.mark.parametrize("name", sorted(json.loads(_UNSCANNED.read_text())["packages"]))
def test_the_unscanned_record_only_shrinks(name: str) -> None:
    """A count may fall and never rise, and a rule that reaches zero leaves the file.

    Recording a number is only worth doing if the number is held. Without this the
    file is a comment: it would read as a plan while the count behind it grew.
    """
    recorded = _recorded()[name]
    actual = collections.Counter(
        violation.rule for violation in check_app(_root(name), package=_package(name))
    )

    grown = sorted(
        f"{rule}: recorded {count}, now {actual[rule]}"
        for rule, count in recorded.items()
        if actual[rule] > count
    )
    assert grown == [], (
        f"{name} gained findings the record does not cover: {grown} — fix them, or "
        f"scan the package properly; UNSCANNED.json only shrinks"
    )

    appeared = sorted(set(actual) - set(recorded))
    assert appeared == [], (
        f"{name} now violates rules it did not before: {appeared} — this record is the "
        "debt that already existed, not a licence to add to it"
    )

    settled = sorted(rule for rule, count in recorded.items() if actual[rule] < count)
    assert settled == [], (
        f"{name} has fewer findings than recorded ({settled}) — lower the counts in "
        "UNSCANNED.json in the same change, so the ratchet keeps its teeth"
    )


def test_a_package_that_empties_leaves_the_record() -> None:
    """The end state this file exists to reach, asserted rather than hoped for."""
    for name, recorded in _recorded().items():
        assert sum(recorded.values()) > 0, (
            f"{name} is recorded as unscanned with no findings left — move it to "
            "_CLEAN (or _BUDGETED) and drop it from UNSCANNED.json"
        )
