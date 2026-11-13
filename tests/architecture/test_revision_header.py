"""``revision_header``: which revision a file is and which it follows, read without running it.

A reader that lists the histories a release carries needs every revision's ``revision``
and ``down_revision``, and importing a revision to learn them would run it. So they are
read from the source, and a header that cannot be read for certain is refused by name
rather than guessed: a reader that guessed a parent would build a history that is not
the one the database will be migrated along.
"""

from __future__ import annotations

import pathlib
import runpy

import pytest

from terp.arch import RevisionHeader, revision_depends_on, revision_header
from tests.architecture.rule_layout import corpus_root

_REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "source,header,parents",
    [
        # A history's first revision, an ordinary one, and a merge.
        ("revision = 'a1'\ndown_revision = None\n", RevisionHeader("a1", None), ()),
        ("revision = 'b2'\ndown_revision = 'a1'\n", RevisionHeader("b2", "a1"), ("a1",)),
        (
            "revision = 'c3'\ndown_revision = ('a1', 'b2')\n",
            RevisionHeader("c3", ("a1", "b2")),
            ("a1", "b2"),
        ),
        # A list is read as the tuple of the same ids, in the same order.
        ("revision = 'c3'\ndown_revision = ['b2', 'a1']\n", RevisionHeader("c3", ("b2", "a1")), ("b2", "a1")),
        ("revision = 'a1'\ndown_revision = ()\n", RevisionHeader("a1", ()), ()),
        # Alembic's current template annotates both.
        (
            "from typing import Sequence, Union\n\n"
            "revision: str = 'b2'\n"
            "down_revision: Union[str, Sequence[str], None] = 'a1'\n"
            "branch_labels: Union[str, Sequence[str], None] = None\n"
            "depends_on: Union[str, Sequence[str], None] = None\n",
            RevisionHeader("b2", "a1"),
            ("a1",),
        ),
        # A bare annotation binds nothing, and a chained assignment is one assignment.
        ("revision: str\nrevision = down = 'b2'\ndown_revision = 'a1'\n", RevisionHeader("b2", "a1"), ("a1",)),
    ],
)
def test_the_header_is_read(source: str, header: RevisionHeader, parents: tuple[str, ...]) -> None:
    assert revision_header(source) == header
    assert revision_header(source).parents == parents


@pytest.mark.parametrize(
    "source,refusal",
    [
        ("down_revision = None\n", "the revision assigns no module-level 'revision'"),
        ("revision = 'a1'\n", "the revision assigns no module-level 'down_revision'"),
        (
            "if True:\n    revision = 'a1'\ndown_revision = None\n",
            "the revision assigns no module-level 'revision'",
        ),
        (
            "revision = 'a1'\nrevision = 'a2'\ndown_revision = None\n",
            "the revision binds 'revision' 2 times at module level",
        ),
        (
            "revision = 'a1'\nrevision += 'x'\ndown_revision = None\n",
            "the revision binds 'revision' 2 times at module level",
        ),
        (
            "revision = 'b2'\ndown_revision = 'a1'\ndown_revision: str = 'a0'\n",
            "the revision binds 'down_revision' 2 times at module level",
        ),
        (
            "revision += 'a1'\ndown_revision = None\n",
            "'revision' must be assigned on its own, as `revision = <literal>`",
        ),
        (
            "revision, down_revision = 'a1', None\n",
            "'revision' must be assigned on its own, as `revision = <literal>`",
        ),
        ("revision = make_id()\ndown_revision = None\n", "'revision' must be assigned a literal"),
        ("revision = {[]: 1}\ndown_revision = None\n", "'revision' must be assigned a literal"),
        (
            "revision = 'b2'\ndown_revision = PARENT\n",
            "'down_revision' must be assigned a literal",
        ),
        ("revision = 5\ndown_revision = None\n", "'revision' must be a string, not 5"),
        (
            "revision = 'c3'\ndown_revision = ('a1', 5)\n",
            "'down_revision' must be None, a string, or a tuple of strings, not ('a1', 5)",
        ),
        (
            "revision = 'b2'\ndown_revision = 5\n",
            "'down_revision' must be None, a string, or a tuple of strings, not 5",
        ),
    ],
)
def test_a_header_that_cannot_be_read_for_certain_is_refused(source: str, refusal: str) -> None:
    with pytest.raises(ValueError) as refused:
        revision_header(source)
    assert str(refused.value) == refusal


def test_source_that_does_not_parse_is_refused() -> None:
    with pytest.raises(SyntaxError):
        revision_header("revision = 'a1'\ndown_revision = (\n")


@pytest.mark.parametrize(
    "source,depends_on",
    [
        # Left out, which Alembic reads as None; and as its template writes it.
        ("revision = 'a1'\ndown_revision = None\n", None),
        ("revision = 'b2'\ndown_revision = 'a1'\ndepends_on: str | None = None\n", None),
        ("revision = 'b2'\ndown_revision = 'a1'\ndepends_on = 'z9'\n", "z9"),
        ("revision = 'b2'\ndown_revision = 'a1'\ndepends_on = ['y8', 'z9']\n", ["y8", "z9"]),
        # A bare annotation binds nothing.
        ("depends_on: str\n", None),
    ],
)
def test_depends_on_is_read_as_written(source: str, depends_on: object) -> None:
    assert revision_depends_on(source) == depends_on


@pytest.mark.parametrize(
    "source,refusal",
    [
        ("depends_on = None\ndepends_on = 'z9'\n", "the revision binds 'depends_on' 2 times at module level"),
        ("depends_on = DEPENDS\n", "'depends_on' must be assigned a literal"),
        ("depends_on, x = None, 1\n", "'depends_on' must be assigned on its own, as `depends_on = <literal>`"),
    ],
)
def test_a_depends_on_that_cannot_be_read_for_certain_is_refused(source: str, refusal: str) -> None:
    with pytest.raises(ValueError) as refused:
        revision_depends_on(source)
    assert str(refused.value) == refusal
    with pytest.raises(SyntaxError):
        revision_depends_on(source + "depends_on = (\n")


def test_the_revision_is_never_executed(tmp_path: pathlib.Path) -> None:
    ran = tmp_path / "ran"
    source = (
        f"import pathlib\npathlib.Path({str(ran)!r}).write_text('module')\n"
        "raise SystemExit('a revision read as data never runs')\n"
        "revision = 'b2'\ndown_revision = 'a1'\n"
    )
    assert revision_header(source) == RevisionHeader("b2", "a1")
    computed = (
        f"revision = __import__('pathlib').Path({str(ran)!r}).write_text('header')\n"
        "down_revision = None\n"
    )
    with pytest.raises(ValueError, match="'revision' must be assigned a literal"):
        revision_header(computed)
    assert not ran.exists()


def _framework_revisions() -> list[pathlib.Path]:
    # The backend corpus beside terp-arch holds sample app trees, some with deliberately
    # broken revisions; they are a rule's test data, not a history this framework ships.
    corpus = corpus_root("backend")
    return [
        path
        for root in ("packages/backend", "apps/example/app")
        for path in sorted((_REPO / root).rglob("migrations/versions/*.py"))
        if not path.name.startswith("_") and not path.is_relative_to(corpus)
    ]


def test_the_framework_has_histories_to_read() -> None:
    assert len(_framework_revisions()) >= 20


@pytest.mark.parametrize(
    "path", _framework_revisions(), ids=lambda path: path.relative_to(_REPO).as_posix()
)
def test_the_header_is_what_alembic_reads(path: pathlib.Path) -> None:
    """Every revision the framework ships reads as the values Alembic gets by running it."""
    module = runpy.run_path(str(path))
    expected = module["down_revision"]
    header = revision_header(path.read_text(encoding="utf-8"))
    assert header.revision == module["revision"]
    assert header.down_revision == (tuple(expected) if isinstance(expected, list) else expected)
    assert revision_depends_on(path.read_text(encoding="utf-8")) == module.get("depends_on")
