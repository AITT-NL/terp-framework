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


#: The base-profile flows every app runs: the helpers, the package's own suite, and the copy
#: of the auth flow the project template ships. Not an app's own module specs, which are the
#: right place for that app's own wording.
_BASE_PROFILE_SOURCES = (
    *sorted((_CONFORMANCE / "src").rglob("*.ts")),
    *sorted((_CONFORMANCE / "tests").rglob("*.ts")),
    _REPO_ROOT / "template/project/conformance/tests/auth.spec.ts",
)

#: A Playwright locator that finds an element by what it SAYS: a label, a text, a placeholder,
#: a title, alt text, or a role narrowed by its accessible name.
_BY_WORDING = re.compile(
    r"getBy(?:Label|Text|Placeholder|Title|AltText)\s*\(|getByRole\s*\([^)]*\bname\s*:"
)


def _code_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """*path*'s lines with comments blanked, so prose quoting the old locators cannot
    count. Block comments keep their newlines, which keeps the line numbers true."""
    text = re.sub(
        r"/\*.*?\*/",
        lambda match: "\n" * match.group(0).count("\n"),
        path.read_text(encoding="utf-8"),
        flags=re.S,
    )
    return [
        (number, re.sub(r"(^|[^:])//.*$", r"\1", line))
        for number, line in enumerate(text.splitlines(), 1)
    ]


def test_the_base_profile_flows_find_nothing_by_its_wording() -> None:
    """A base-profile flow must pass in every locale an app can ship.

    The helpers found the sign-in screen by "Sign in", "Email" and "Password" and sign-out
    by "Sign out" — English sentences, in a framework whose project template starts an app
    in Dutch. So a freshly generated app failed its own conformance suite on the login screen
    before it had written a line of code, and the framework's own lane could not see it
    because the example app it runs on is English.

    What the flows still owe a user of assistive technology is carried by the helpers' own
    assertion that every control has a role and a non-empty accessible name — which checks
    that a name exists without choosing its language.
    """
    assert all(path.is_file() for path in _BASE_PROFILE_SOURCES)
    offenders = [
        f"{path.relative_to(_REPO_ROOT).as_posix()}:{number}: {line.strip()}"
        for path in _BASE_PROFILE_SOURCES
        for number, line in _code_lines(path)
        if _BY_WORDING.search(line)
    ]
    assert offenders == [], (
        "these base-profile flows find an element by its wording, which is the app's language "
        "and not the framework's; locate it by its data-terp marker instead:\n  "
        + "\n  ".join(offenders)
    )
