"""``terp fmt`` — format the code you touched, not the code you didn't.

``ruff format .`` is the right formatter with the wrong blast radius. Run it on a
project whose history predates the current ruff version — or that has a single
file someone once formatted by hand — and it rewrites files the current change
never touched. The diff that reaches review is then part change and part churn,
and the author's only recourse is to ``git checkout`` the unrelated files one by
one, which is a manual step at exactly the moment they were trying to automate.

So the default is ``--changed``: the files git reports as modified, staged or
untracked relative to HEAD. That is the set the author is responsible for, and it
is the set a pre-commit hook wants. ``--all`` is still there for the deliberate
whole-tree pass, but it has to be asked for.

Formatting a *subset* is safe here because ruff's formatter is per-file and
deterministic; there is no cross-file state that a partial run could leave
inconsistent.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

__all__ = ["changed_python_files", "run_fmt_command"]


def changed_python_files(root: str | pathlib.Path = ".") -> list[pathlib.Path]:
    """Python files modified, staged or untracked relative to HEAD, under *root*.

    Deleted paths are dropped — a formatter cannot rewrite a file that is gone,
    and passing one to ruff turns a clean run into an error about a missing file.
    Returns an empty list outside a git work tree, which the caller reports as
    "nothing to format" rather than silently falling back to the whole tree.
    """
    base = pathlib.Path(root)
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    paths: list[pathlib.Path] = []
    for line in result.stdout.splitlines():
        status, name = line[:2], line[3:]
        if "D" in status:
            continue
        name = name.split(" -> ")[-1].strip('"')
        if not name.endswith(".py"):
            continue
        candidate = base / name
        if candidate.is_file():
            paths.append(candidate)
    return sorted(set(paths))


def run_fmt_command(
    *, root: str | pathlib.Path = ".", changed: bool = True, check: bool = False
) -> int:
    """Run ruff's formatter over the changed files (or the whole tree with *changed* off).

    Returns the process exit code so the caller can propagate it. ``check`` maps to
    ``ruff format --check``, which reports what would be rewritten without touching
    anything — the shape CI wants.
    """
    base = pathlib.Path(root)
    if changed:
        targets = [str(path.relative_to(base)) for path in changed_python_files(base)]
        if not targets:
            print("terp fmt: no changed Python files to format")
            return 0
    else:
        targets = ["."]
    argv = [sys.executable, "-m", "ruff", "format", *(["--check"] if check else []), *targets]
    try:
        return subprocess.run(argv, cwd=base, check=False).returncode  # noqa: S603
    except OSError:
        print(
            "terp fmt: ruff is not installed in this interpreter; add it as a dev "
            "dependency (uv add --dev ruff) and retry.",
            file=sys.stderr,
        )
        return 2
