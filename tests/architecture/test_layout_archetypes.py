"""Every enumeration of the page archetypes lists all of them.

`FormPage`, `SettingsPage` and `SplitPage` shipped in 0.10.0 and four documents went on
naming three — including the generated app's own `AGENTS.md`, so a new app was briefed to
not know about half the archetypes it is required to use. Nothing was wrong in the code and
nothing failed; the briefing was simply a release behind.

The set comes from the layout contract, which is where it is already normative (the
build-time slot table and the runtime resolver both read it), because a list maintained here
is the very thing that went stale.

**The unit is one enumeration, not one file, and that distinction is the whole gate.** A
per-file check passes as soon as the file mentions every name *somewhere* — so a document
carrying two lists satisfies it with one of them correct, which is how a stale list survives
in a file that also has a fresh one. Proven by mutation: emptying one of `template/AGENTS.md`'s
two lists left a per-file check green.

An enumeration is a paragraph naming two or more archetypes: that is what a list looks like
whether it is written on one line or wrapped over several. A paragraph naming exactly one is
prose or a table row about that archetype, and is deliberately not held to the whole set.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONTRACT = (
    _REPO_ROOT / "packages" / "frontend" / "react-core" / "src" / "layoutContract.ts"
)

#: Documents that brief a reader on which archetypes exist. The first two are what a
#: generated app and its agents read, which is where a stale list does real damage.
_ENUMERATING_DOCS = (
    "template/project/AGENTS.md.jinja",
    "template/AGENTS.md",
    "packages/frontend/react-core/README.md",
)


def _shipped_archetypes() -> frozenset[str]:
    """The archetype names the layout contract declares slot tables for.

    ``Page`` is excluded: it is the base every archetype composes, not a peer in the table.
    """
    source = _CONTRACT.read_text(encoding="utf-8")
    found = frozenset(re.findall(r"^\s{6}([A-Z][A-Za-z]*Page): \{", source, re.M))
    assert len(found) >= 6, (
        f"the layout contract yielded only {sorted(found)} — this gate reads the archetype "
        "set from it, so a parsing change here silently stops enforcing anything"
    )
    return found


def test_every_enumeration_of_the_archetypes_lists_all_of_them() -> None:
    shipped = _shipped_archetypes()
    problems: list[str] = []

    for rel in _ENUMERATING_DOCS:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        for index, paragraph in enumerate(re.split(r"\n\s*\n", text)):
            named = {name for name in shipped if name in paragraph}
            # One name is prose or a table row about that archetype; two or more is a list.
            if len(named) < 2:
                continue
            missing = sorted(shipped - named)
            if missing:
                excerpt = " ".join(paragraph.split())[:140]
                problems.append(f"{rel} (paragraph {index}): omits {missing} — {excerpt!r}")

    assert not problems, (
        "these enumerations name a SUBSET of the page archetypes, and a reader briefed on a "
        "subset uses the subset — the omitted archetypes ship, the router accepts them, and "
        "nothing tells the author they exist:\n  " + "\n  ".join(problems)
    )
