"""``terp fmt`` formats the change, not the tree.

A formatter that rewrites files the current change never touched turns a review
diff into part signal and part churn, and leaves the author manually reverting
files — a hand step at the exact moment they were automating one. So the default
is the changed set, and the whole-tree pass has to be asked for.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from terp.cli import changed_python_files, run_fmt_command


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "gate@terp.test")
    _git(tmp_path, "config", "user.name", "Gate")
    (tmp_path / "untouched.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_changed_set_excludes_committed_files(repo: pathlib.Path) -> None:
    """A file nobody touched is not this change's business, however it is formatted."""
    assert changed_python_files(repo) == []

    (repo / "new_module.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "untouched.py").write_text("x = 1\nz = 3\n", encoding="utf-8")
    changed = {path.name for path in changed_python_files(repo)}
    assert changed == {"new_module.py", "untouched.py"}


def test_changed_set_drops_deletions_and_non_python(repo: pathlib.Path) -> None:
    """A deleted path cannot be reformatted, and passing it to ruff fails the run."""
    (repo / "untouched.py").unlink()
    (repo / "notes.md").write_text("# hi\n", encoding="utf-8")
    assert changed_python_files(repo) == []


def test_fmt_is_a_no_op_when_nothing_changed(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence is not success — the command says it found nothing, and exits clean."""
    assert run_fmt_command(root=repo) == 0
    assert "no changed Python files" in capsys.readouterr().out


def test_outside_a_git_work_tree_the_changed_set_is_empty(tmp_path: pathlib.Path) -> None:
    """Fail closed to "nothing", never open to "the whole tree".

    Silently formatting everything because git was unavailable is precisely the
    blast radius this command exists to avoid.
    """
    assert changed_python_files(tmp_path) == []
