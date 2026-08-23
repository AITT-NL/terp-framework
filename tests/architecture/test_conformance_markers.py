"""Every `data-terp` marker the conformance suite reaches for is a real one.

``@terpjs/conformance`` drives a running Terp app through the browser, and its
helpers are the sign-in and sign-out flows every app's own e2e suite composes.
That makes it a **consumer of react-core's rendered DOM from another package**,
and the only lane that can see the coupling boots Postgres, the API and the web
app in Docker. When it disagrees with the components, nothing local says so.

It disagreed for thirty-six commits. ``logout()`` located the account menu by
the accessible name ``"Account menu"``, which stopped being that button's name
when the expanded trigger started taking its name from the user's email and role
instead (WCAG 2.5.3, Label in Name — an ``aria-label`` replaces subtree text, so
naming it hid what the user could see). The break shipped in the same push as
thirty-five other commits because none of them had been pushed, so CI had never
run on any of them.

The helper reaches for markers now, which are the stable axis: the inventory is
pinned by ``markers.test.ts`` and a rename is a release note. This test is the
other half of that bargain — a marker the suite depends on must be a marker the
package actually renders, checked without booting anything.

It does not, and cannot, verify that a marker is rendered in the *state* the
helper meets it in. That part is a unit test next to the component.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_CONFORMANCE = _REPO_ROOT / "packages/frontend/conformance"
_MARKERS_TEST = _REPO_ROOT / "packages/frontend/react-core/src/markers.test.ts"

# `data-terp="…"` inside a selector string, which is how a Playwright locator names one.
_MARKER_REF = re.compile(r'data-terp=\\?"([a-z0-9-]+)\\?"')

# The pinned inventory, read out of the array `markers.test.ts` holds by exact equality.
_MARKERS_ARRAY = re.compile(r"const MARKERS = \[(.*?)\n\];", re.S)
_MARKER_ENTRY = re.compile(r'"([a-z0-9-]+)"')


def _pinned_markers() -> set[str]:
    body = _MARKERS_ARRAY.search(_MARKERS_TEST.read_text(encoding="utf-8"))
    assert body is not None, "could not find the MARKERS array in markers.test.ts"
    return set(_MARKER_ENTRY.findall(body.group(1)))


def _referenced_markers() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(_CONFORMANCE.rglob("*.ts")):
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        names = set(_MARKER_REF.findall(path.read_text(encoding="utf-8", errors="replace")))
        if names:
            found[path.relative_to(_REPO_ROOT).as_posix()] = names
    return found


def test_the_pinned_inventory_is_readable() -> None:
    """Both halves of the comparison have to be non-empty or the test proves nothing."""
    markers = _pinned_markers()
    assert len(markers) > 100, f"only parsed {len(markers)} markers; the reader is broken"
    assert "user-menu" in markers and "menu-trigger" in markers


def test_the_suite_reaches_for_at_least_one_marker() -> None:
    """If the helpers stop using markers entirely this test should be deleted, not left passing.

    Without it, a refactor that replaced every marker locator with something else would leave the
    comparison below quietly comparing nothing — the same empty-set pass this repository has been
    bitten by in three other scans.
    """
    referenced = _referenced_markers()
    assert referenced != {}, (
        "no data-terp locator found in the conformance suite; if that is deliberate, delete this "
        "module rather than leaving a vacuous check behind"
    )


def test_every_marker_the_conformance_suite_uses_exists() -> None:
    pinned = _pinned_markers()
    unknown = {
        rel: sorted(names - pinned) for rel, names in _referenced_markers().items() if names - pinned
    }
    assert unknown == {}, (
        "these locators name a data-terp marker no component renders, so they can only ever time "
        f"out: {unknown}"
    )
