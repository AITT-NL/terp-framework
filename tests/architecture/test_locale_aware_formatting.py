"""Nothing asks the host a question the app has already answered.

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

**Case folding is covered too, and for a sharper reason.** An earlier version of
this file exempted ``toLocaleLowerCase`` / ``toLocaleUpperCase`` on the grounds
that they fold case rather than present a value. That rationale does not hold:
``Combobox`` used one to decide whether a typed needle *matches* an option
label, and folded against a Turkish host ``Item`` becomes ``ıtem`` — dotless —
which does not contain the ``i`` the user typed. Every option with a capital I
vanished for a Turkish visitor and for nobody else. Folding both sides with the
same host locale does not rescue it, because the needle comes from a keyboard
and the haystack from a server. A fold used for matching must be invariant, so
the bare form is refused here rather than excused.

Why a build-time scan rather than a unit test: the defect is invisible to almost
every runtime check this repository has. Only one admin screen has a specimen
(``admin-user-create``) and it renders no date, so nothing pictures these cells;
no assertion covered their text before this work; and on a Dutch host — which is
what runs this suite — the wrong answer and the right answer are frequently the
same string, so even a unit test written against a single locale passes under the
bug. That is not hypothetical: it happened twice while this rule was being
written, and a mutation is what caught it both times.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_THIS_FILE = pathlib.Path(__file__).resolve()

# Where app-facing TypeScript lives. `template/` carries `.jinja` sources too.
_TREES = ("packages/frontend", "apps", "template")
_SUFFIXES = {".ts", ".tsx", ".jinja"}

# The defect shape: a locale-sensitive operation invoked with NO argument.
#
# `new` is optional on the Intl constructors because they are specified to work
# called as plain functions — `Intl.NumberFormat().format(x)` is legal, returns a
# working instance and produces byte-identical wrong output, so a pattern that
# required the keyword would miss half the spellings of the same mistake.
_NO_LOCALE = re.compile(
    r"\.toLocale(?:Date|Time)?String\(\s*\)"
    r"|\.toLocale(?:Lower|Upper)Case\(\s*\)"
    r"|\.localeCompare\(\s*\)|\.localeCompare\([^,]*,\s*undefined"
    r"|(?:new\s+)?Intl\.(?:DateTimeFormat|NumberFormat|RelativeTimeFormat|ListFormat"
    r"|PluralRules|Collator|DisplayNames|Segmenter)\(\s*\)"
)

# Spellings the pattern MUST see, and spellings it must leave alone. These are
# literals rather than repository content on purpose: every other assertion in
# this file is about what the repo contains, so all of them go quiet together the
# moment the pattern stops matching anything. This one does not.
_MUST_MATCH = (
    "new Date(x).toLocaleDateString()",
    "d.toLocaleString()",
    "d.toLocaleTimeString()",
    "q.toLocaleLowerCase()",
    "label.toLocaleUpperCase()",
    "a.localeCompare(b, undefined, { numeric: true })",
    "a.localeCompare()",
    "new Intl.DateTimeFormat().format(d)",
    "Intl.DateTimeFormat().format(d)",
    "Intl.NumberFormat().format(n)",
    "new Intl.NumberFormat( ).format(n)",
    "new Intl.Collator().compare(a, b)",
)
_MUST_NOT_MATCH = (
    'd.toLocaleDateString("nl")',
    "d.toLocaleDateString(locale)",
    'new Intl.DateTimeFormat(locale, { year: "numeric" })',
    "new Intl.NumberFormat(locale, options)",
    "value.toLowerCase()",
    "value.toUpperCase()",
    'a.localeCompare(b, locale)',
    'a.localeCompare(b, "nl")',
    # A bare two-argument compare is not matched: it has no locale slot to omit.
    "a.localeCompare(b)",
    # Prose about the rule must not trip the rule: no receiver, so no match.
    "formatted with toLocaleDateString() and no locale argument",
)

# Files allowed to contain a matching literal, each for a reason that is not "it
# formats a date". A stale entry fails too (see below), so this cannot rot into a
# blanket exemption.
_ALLOWED: dict[str, str] = {
    "packages/frontend/react-core/src/dataview/repositories/InMemoryDataViewRepository.ts": (
        "sorts with an explicit `undefined` locale, so an in-memory DataView orders rows "
        "by the VISITOR's collation rather than the app's. Pre-dates this rule and is not "
        "a one-line fix: a repository is constructed by the app, usually at module scope, "
        "and has no route to `LocaleProvider`. Closing it means a `locale` option on "
        "`InMemoryDataViewRepositoryOptions` (or building the repository inside a hook), "
        "which is an API decision rather than a correction. `sensitivity: \"base\"` already "
        "removes the accent and case variation; what is left is alphabet order, which "
        "differs in a handful of locales. Listed so the gap is recorded and so no SECOND "
        "one can be added quietly"
    ),
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
        hits = _NO_LOCALE.findall(path.read_text(encoding="utf-8", errors="replace"))
        if hits:
            found[rel] = hits
    return found


def test_the_pattern_matches_the_spellings_it_claims_to() -> None:
    """The scan's own regex, checked against literals rather than repo content."""
    missed = [sample for sample in _MUST_MATCH if not _NO_LOCALE.search(sample)]
    assert missed == [], f"the pattern cannot see these: {missed}"
    caught = [sample for sample in _MUST_NOT_MATCH if _NO_LOCALE.search(sample)]
    assert caught == [], f"the pattern wrongly flags these: {caught}"


def test_the_scan_can_see_the_trees_it_claims_to_scan() -> None:
    """A scan over an empty file list passes everything.

    A wrong tree name, a suffix that matches nothing, or a `node_modules` filter
    that swallows the whole package would leave every content assertion here
    vacuously true and the build green.
    """
    sources = _sources()
    assert len(sources) > 200, f"only found {len(sources)} sources; the scan is not reaching them"
    seen = {p.relative_to(_REPO_ROOT).parts[0] for p in sources}
    assert seen == {"packages", "apps", "template"}, seen
    assert any(
        p.as_posix().endswith("react-core/src/format.ts")
        for p in (s.relative_to(_REPO_ROOT) for s in sources)
    )


def test_no_locale_sensitive_call_omits_its_locale() -> None:
    offenders = {rel: hits for rel, hits in _offenders().items() if rel not in _ALLOWED}
    assert offenders == {}, (
        "these ask the host a question the app has already answered — format dates "
        "and numbers with useFormatDate / useFormatDateTime / useFormatNumber from "
        f"@terpjs/react-core, and fold case for matching with toLowerCase: {offenders}"
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    """An allowlist that outlives its reason is how a ratchet becomes a rubber stamp."""
    offenders = _offenders()
    stale = sorted(set(_ALLOWED) - set(offenders))
    assert stale == [], (
        "these are allowlisted but no longer contain the literal, so the entry "
        f"is stale and should be deleted: {stale}"
    )
