"""The in-terminal guide's code snippets must be real, compiled code.

`terp guide <topic>` is the first thing an author is told to reach for, so a snippet
in it that does not compile is a defect in the platform, not a typo in a docstring.
This happened: the ``dataview`` topic taught a constructor arity, a ``keyField`` prop
and a column shape that had all never existed, while the package README next to it was
correct throughout — the worst possible split.

The fix is a fixture the workspace typecheck compiles
(``packages/frontend/react-core/src/guide/guideSnippets.tsx``): the blocks it marks with
``terp-guide-snippet`` are the exact lines the guide prints. This test is the other half
— it pins guide text to compiled code, so a snippet can only rot if someone edits both.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from terp.cli import _GUIDE_TOPICS

_SNIPPETS = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "frontend"
    / "react-core"
    / "src"
    / "guide"
    / "guideSnippets.tsx"
)

_BLOCK = re.compile(
    r"// terp-guide-snippet: (?P<topic>\w+)\n(?P<body>.*?)^\s*// terp-guide-snippet-end",
    re.DOTALL | re.MULTILINE,
)


def _blocks() -> list[tuple[str, str]]:
    return [(m["topic"], m["body"]) for m in _BLOCK.finditer(_SNIPPETS.read_text(encoding="utf-8"))]


def test_the_snippet_fixture_exists_and_is_marked_up() -> None:
    assert _blocks(), f"no marked guide snippets in {_SNIPPETS}"


@pytest.mark.parametrize("topic,body", _blocks())
def test_guide_snippets_are_compiled_code(topic: str, body: str) -> None:
    assert topic in _GUIDE_TOPICS, f"snippet marked for unknown guide topic {topic!r}"
    guide_lines = {line.strip() for line in _GUIDE_TOPICS[topic].splitlines()}
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            assert stripped in guide_lines, (
                f"`terp guide {topic}` no longer prints the compiled line {stripped!r}. "
                f"The guide and {_SNIPPETS.name} must move together — a guide snippet "
                "that nothing compiles is how the DataView topic came to teach an API "
                "that never existed."
            )
