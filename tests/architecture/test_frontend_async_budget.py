"""The component tests' async budget sits between three bounds, in three files.

Testing Library's ``findBy*`` default of 1000ms is not enough for react-core's component
tests — that second covers a mocked fetch resolving, the state it sets and the re-render
that puts the text on screen, which is fine on an idle machine and not on a loaded one.
Raising it is not free in one direction only, and the ceiling is what makes this a guard
rather than a comment: a toast auto-dismisses after ``DEFAULT_DURATION_MS``, and several
admin tests wait for a field error and then assert the toast SYNCHRONOUSLY. A budget at
or above that duration lets a slow wait outlive the thing the next line reads — which
presents as a product bug, not a configuration one. The first attempt at the fix did
exactly that and broke a test that had never flaked.

So three numbers in three files have to stay ordered, and no one of them knows about the
others:

    1000ms (the library default)  <  asyncUtilTimeout  <  DEFAULT_DURATION_MS  <  testTimeout

Held here rather than in the suite itself because it spans those files: react-core
compiles with ``types: []`` and reading files from a test there needs node types the
package deliberately does not have. That the ``configure`` call took effect at all — as
opposed to a number sitting unused in a setup file — is asserted from inside the suite,
in ``src/async-budget.test.ts``.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_REACT_CORE = _REPO_ROOT / "packages" / "frontend" / "react-core"

#: Testing Library's own default, and the reason this file exists.
_LIBRARY_DEFAULT_MS = 1000


def _declared(path: pathlib.Path, pattern: str) -> int:
    """The one number ``pattern`` names in ``path``, underscores allowed (``15_000``)."""
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, f"{path.name} declares no {pattern!r}"
    return int(match.group(1).replace("_", ""))


def _async_budget_ms() -> int:
    return _declared(
        _REACT_CORE / "vitest.setup.ts", r"asyncUtilTimeout:\s*([\d_]+)"
    )


def _toast_duration_ms() -> int:
    return _declared(_REACT_CORE / "src" / "toast.tsx", r"DEFAULT_DURATION_MS\s*=\s*([\d_]+)")


def _test_timeout_ms() -> int:
    return _declared(_REACT_CORE / "vite.config.ts", r"testTimeout:\s*([\d_]+)")


def test_the_async_budget_clears_the_library_default() -> None:
    """Below this the flakes come back: the default is what they were traced to."""
    assert _async_budget_ms() > _LIBRARY_DEFAULT_MS


def test_the_async_budget_stays_under_a_toast_lifetime() -> None:
    """A wait must not outlive a toast the next line asserts synchronously.

    Strictly under, not equal: at equality the two timers race, and which one wins is
    the machine's mood — the failure mode this guard exists to make impossible to
    reintroduce, since it reads as the product misbehaving.
    """
    assert _async_budget_ms() < _toast_duration_ms()


def test_a_failing_matcher_reports_before_the_test_times_out() -> None:
    """The matcher must lose first, so the failure names the element it could not find.

    With ``testTimeout`` the smaller of the two, a genuinely failing assertion is cut off
    mid-wait and reported as "test timed out", which says nothing about what was awaited.
    """
    assert _test_timeout_ms() > _async_budget_ms()
