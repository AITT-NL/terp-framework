"""One parse per file per run, and no stale tree ever.

The harness runs every rule over the same tree and each rule walked and parsed it
independently: 2,354 ``ast.parse`` calls over a 32-file tree, because the redundancy
factor is the RULE COUNT — 79 today, and only ever up. The cost is linear in two things
that both only grow, and the consumer who feels it is the one with the biggest app.

The fix is a memo scoped to one scan rather than cached on the module, and the scoping
is the whole design. A process-global cache would answer from a stale tree the moment
anything rewrote a file between scans — which is exactly what this repository's own rule
tests do, and what an editor or a workbench does continuously. Keying on ``st_mtime_ns``
would paper over most of that and still lose to two writes inside one timestamp tick.

So these tests are mostly about what the cache must NOT do.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap

from terp.arch._ast import iter_python_files, parse, scan_cache
from terp.arch.rules import (
    _ALL_RULES,
    RootKind,
    _apply_suppressions,
    _scan_allow_markers,
    check_app,
    root_kinds_for,
)


def _write(path: pathlib.Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def test_outside_a_run_every_parse_reads_the_file_again(tmp_path: pathlib.Path) -> None:
    """The property the rule tests depend on: write, check, rewrite, check again.

    A module-level cache would hand the second check the first file's tree, and the
    test would pass or fail on the wrong source with nothing to say so.
    """
    module = tmp_path / "m.py"
    _write(module, "x = 1\n")
    first = ast.dump(parse(module))
    _write(module, "y = 2\n")
    second = ast.dump(parse(module))
    assert first != second, (
        "parse() answered from a cached tree outside a scan — a rewritten file must be "
        "re-read, or every caller that edits between scans silently analyses stale source"
    )


def test_inside_a_run_the_same_file_is_parsed_once(tmp_path: pathlib.Path) -> None:
    module = tmp_path / "m.py"
    _write(module, "x = 1\n")
    with scan_cache():
        assert parse(module) is parse(module), (
            "inside a scan the same path must yield the SAME tree — that identity is "
            "the whole saving, and it is sound only because no rule mutates one"
        )


def test_a_run_never_outlives_itself(tmp_path: pathlib.Path) -> None:
    """The memo is released with the context, so the next scan starts from the disk."""
    module = tmp_path / "m.py"
    _write(module, "x = 1\n")
    with scan_cache():
        first = parse(module)
    _write(module, "y = 2\n")
    with scan_cache():
        second = parse(module)
    assert ast.dump(first) != ast.dump(second)


def test_a_nested_run_shares_the_outer_memo(tmp_path: pathlib.Path) -> None:
    """A rule that composes another rule must not pay for a second parse — and must
    not get a second, divergent tree either."""
    module = tmp_path / "m.py"
    _write(module, "x = 1\n")
    with scan_cache():
        outer = parse(module)
        with scan_cache():
            inner = parse(module)
        assert outer is inner
        # ... and the inner block's exit did not tear down the outer memo.
        assert parse(module) is outer


def test_the_file_listing_is_an_iterator_each_time(tmp_path: pathlib.Path) -> None:
    """Memoising the walk must not hand out an exhausted iterator on the second call —
    every rule calls this, so one rule consuming it would blind all the rest."""
    _write(tmp_path / "a.py", "x = 1\n")
    _write(tmp_path / "pkg" / "b.py", "y = 2\n")
    with scan_cache():
        first = list(iter_python_files(tmp_path))
        second = list(iter_python_files(tmp_path))
    assert first == second and len(first) == 2, (first, second)


def test_the_listing_still_honours_the_skip_set(tmp_path: pathlib.Path) -> None:
    """Two callers with different skip sets share a run and must not share an answer:
    the security rules deliberately scan `tests/` and the rest deliberately do not."""
    from terp.arch._ast import _SECURITY_SKIP_DIRS

    _write(tmp_path / "app.py", "x = 1\n")
    _write(tmp_path / "tests" / "test_x.py", "y = 2\n")
    with scan_cache():
        default = [p.name for p in iter_python_files(tmp_path)]
        security = [p.name for p in iter_python_files(tmp_path, skip_dirs=_SECURITY_SKIP_DIRS)]
    assert default == ["app.py"], default
    assert sorted(security) == ["app.py", "test_x.py"], security


def _dirty_app(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "app"
    _write(root / "__init__.py", "")
    _write(root / "modules" / "__init__.py", "")
    _write(root / "modules" / "notes" / "__init__.py", "")
    _write(
        root / "main.py",
        """
        from terp.core import create_app
        app = create_app([])
        app.mount("/static", object())
        @app.get("/raw")
        def raw() -> dict:
            return {}
        """,
    )
    _write(
        root / "modules" / "notes" / "router.py",
        """
        from fastapi import HTTPException
        def boom():
            raise HTTPException(status_code=404)
        def q(name):
            return "SELECT * FROM t WHERE n = '" + name + "'"
        """,
    )
    return root


def test_the_cache_changes_the_cost_and_not_the_verdict(tmp_path: pathlib.Path) -> None:
    """The assertion that matters, on a tree that actually violates things.

    Run every rule directly, outside any scan — the pre-cache code path — and compare
    against what ``check_app`` reports with the memo in place. An empty list equalling
    an empty list would prove nothing, so this tree is deliberately dirty.
    """
    root = _dirty_app(tmp_path)

    cached = check_app(root)

    raw = []
    for rule in _ALL_RULES:
        if RootKind.APP not in root_kinds_for(rule.__name__.removeprefix("check_")):
            continue
        raw.extend(rule(root, package="app"))
    uncached = sorted(
        _apply_suppressions(raw, _scan_allow_markers(root)),
        key=lambda violation: (violation.path, violation.line, violation.rule),
    )

    assert len(cached) > 5, f"the fixture stopped being dirty: {cached}"
    assert cached == uncached, (
        "memoising the scan changed the findings — it may only change the cost:\n"
        f"  only cached:   {sorted(set(cached) - set(uncached))}\n"
        f"  only uncached: {sorted(set(uncached) - set(cached))}"
    )


def test_the_harness_parses_each_file_about_once(tmp_path: pathlib.Path) -> None:
    """A regression guard with a real number behind it: before the memo this was 2,354
    parses for 32 files, and the multiplier was the rule count."""
    root = _dirty_app(tmp_path)
    files = len(list(iter_python_files(root)))

    calls = 0
    original = ast.parse

    def counting(*args: object, **kwargs: object) -> ast.Module:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    ast.parse = counting  # type: ignore[assignment]
    try:
        check_app(root)
    finally:
        ast.parse = original  # type: ignore[assignment]

    # Not exactly `files`: the security rules scan a wider set (they do not skip
    # `tests/`), so a handful of paths are parsed under two different listings. The
    # bound that matters is that it does not scale with the rule count.
    assert calls <= files * 3, (
        f"{calls} parses for {files} files — the per-run memo is not being used, so the "
        f"harness is back to re-parsing the tree once per rule ({len(_ALL_RULES)} rules)"
    )
