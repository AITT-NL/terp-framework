"""The generated rule pages cannot lie (docs/rules/ <-> catalog parity).

``docs/rules/<surface>/<rule>.md`` is generated from the catalog by
``tools/generate_rule_docs.py`` so non-technical readers get each rule's what / why /
what-to-do-instead / opt-out without reading JSON. Regenerating must reproduce the
checked-in pages byte for byte (stale, edited-by-hand or orphaned pages fail), so a
catalog change cannot ship without its page.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))

from generate_rule_docs import _DOCS, generate


def test_generated_rule_docs_match_the_catalog() -> None:
    expected = generate()
    assert len(expected) > 100, "the generator found too few catalog entries to be reading the catalog"
    for path, content in expected.items():
        rel = path.relative_to(_ROOT)
        assert path.is_file(), f"{rel} is missing — run `python tools/generate_rule_docs.py`"
        assert path.read_text(encoding="utf-8") == content, (
            f"{rel} is stale or hand-edited — run `python tools/generate_rule_docs.py`"
        )


def test_no_orphan_rule_docs() -> None:
    expected = set(generate())
    on_disk = set(_DOCS.rglob("*.md"))
    orphans = sorted(p.relative_to(_ROOT) for p in on_disk - expected)
    assert orphans == [], f"rule pages without a catalog entry: {orphans}"


def test_the_generator_writes_exactly_the_pages_it_describes(tmp_path, monkeypatch) -> None:
    """``main()`` is what a person runs; it writes every page ``generate()`` describes, and
    nothing else, so regenerating can never leave the checked-in pages half-written."""
    import generate_rule_docs

    pages = {path.relative_to(_DOCS): content for path, content in generate().items()}
    monkeypatch.setattr(generate_rule_docs, "_DOCS", tmp_path / "docs" / "rules")
    generate_rule_docs.main()
    written = {
        path.relative_to(tmp_path / "docs" / "rules"): path.read_text(encoding="utf-8")
        for path in (tmp_path / "docs" / "rules").rglob("*.md")
    }
    assert written == pages
