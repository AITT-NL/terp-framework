"""No date or number is formatted without a locale.

``value.toLocaleDateString()`` with no argument does not mean "use the default
locale" in any useful sense — it asks the **browser**, so an app that ships one
language through ``LocaleProvider`` renders its own tables in whatever the
visitor's OS is set to. Seven places in ``@terpjs/react-core`` and five in the
example app did exactly that, one row above a ``DatePicker`` that got it right,
because the locale-correct helper existed but was private.

The helpers are ``@terpjs/react-core``'s ``useFormatDate`` /
``useFormatDateTime`` / ``useFormatNumber`` (and the locale-explicit
``formatDate`` / ``formatDateTime`` / ``formatNumber`` beside them). Passing an
explicit ``undefined`` **through** one of those is fine and is the documented
fallback for a caller with no provider; what this refuses is the argument never
being offered at all.

Why a build-time scan rather than a unit test: the defect is invisible to every
runtime check this repository has. No admin screen has a specimen, so nothing
pictures these cells; no assertion covered their text; and on a Dutch host the
wrong answer and the right answer are the same string, so even a unit test
written against one locale passes. A scan is the only control that sees it.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_THIS_FILE = pathlib.Path(__file__).resolve()

# Where app-facing TypeScript lives. `template/` carries `.jinja` sources too.
_TREES = ("packages/frontend", "apps", "template")
_SUFFIXES = {".ts", ".tsx", ".jinja"}

# The defect shape: a locale-sensitive formatter invoked with NO argument.
#
# `toLocaleLowerCase` / `toLocaleUpperCase` are deliberately not matched. They are
# locale-sensitive too, but for casing rather than presentation, and `Combobox`
# calls them on purpose to fold a search needle.
_NO_LOCALE = re.compile(
    r"\.toLocale(?:Date|Time)?String\(\s*\)|new\s+Intl\.(?:DateTime|Number)Format\(\s*\)"
)

# Files allowed to contain the literal, each for a reason that is not "it formats
# a date". A stale entry fails too (see the second test), so this cannot rot into
# a blanket exemption.
# `format.ts` is deliberately NOT here. Its docstring names the defect, but writes
# it as `toLocaleDateString()` with no receiver, and the pattern requires the dot —
# so prose about the rule does not trip the rule. The stale-entry test below is what
# established that: the entry was written on the assumption it would be needed.
_ALLOWED: dict[str, str] = {
    "packages/frontend/react-core/src/admin/admin.test.tsx": (
        "asserts the old spelling is ABSENT from the rendered audit row — the "
        "negative half of the gate that proves the column was converted"
    ),
}


def _sources() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for tree in _TREES:
        root = _REPO_ROOT / tree
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.suffix in _SUFFIXES
                and path.is_file()
                and path.resolve() != _THIS_FILE
                and "node_modules" not in path.parts
                and "dist" not in path.parts
                and ".cache" not in path.parts
            ):
                files.append(path)
    return files


def _offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _sources():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = _NO_LOCALE.findall(text)
        if hits:
            found[rel] = hits
    return found


def test_the_scan_can_see_the_trees_it_claims_to_scan() -> None:
    """A scan over an empty file list passes everything.

    This is the failure this file would otherwise be most likely to ship with:
    a wrong tree name, a suffix that matches nothing, or a `node_modules` filter
    that swallows the whole package would leave every other assertion here
    vacuously true and the build green.
    """
    sources = _sources()
    assert len(sources) > 200, f"only found {len(sources)} sources; the scan is not reaching them"
    seen = {p.relative_to(_REPO_ROOT).parts[0] for p in sources}
    assert seen == {"packages", "apps", "template"}, seen
    # And it can see the file the helpers live in, which every other assertion is about.
    assert any(
        p.as_posix().endswith("react-core/src/format.ts")
        for p in (s.relative_to(_REPO_ROOT) for s in sources)
    )


def test_no_date_or_number_is_formatted_without_a_locale() -> None:
    offenders = {rel: hits for rel, hits in _offenders().items() if rel not in _ALLOWED}
    assert offenders == {}, (
        "these format a date or number with no locale, so they render in the "
        "visitor's locale rather than the app's — use useFormatDate / "
        f"useFormatDateTime / useFormatNumber from @terpjs/react-core: {offenders}"
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    """An allowlist that outlives its reason is how a ratchet becomes a rubber stamp."""
    offenders = _offenders()
    stale = sorted(set(_ALLOWED) - set(offenders))
    assert stale == [], (
        "these are allowlisted but no longer contain the literal, so the entry "
        f"is stale and should be deleted: {stale}"
    )
