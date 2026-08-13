"""Coverage gate: the seam proposal's own branches, and ``terp fmt``'s.

Both are new surfaces whose interesting behaviour is in the branches a happy path
never reaches: a file with no seam to propose, a name shape the component walk has
to skip, a formatter that isn't installed. A gap here is a gap in the two places
this release claims to have made a message useful.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

from terp.arch.rules.size import _definition_components, _proposed_seam
from terp.cli import main
from terp.cli.fmt import changed_python_files, run_fmt_command


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# the seam proposal
# --------------------------------------------------------------------------- #
def test_a_file_without_top_level_definitions_has_no_components(
    tmp_path: pathlib.Path,
) -> None:
    path = _write(tmp_path, "import os\n\nprint(os.name)\n")
    assert _definition_components(ast.parse(path.read_text(encoding="utf-8"))) == []
    assert _proposed_seam(path) == ""


def test_unparseable_source_proposes_nothing(tmp_path: pathlib.Path) -> None:
    assert _proposed_seam(_write(tmp_path, "def broken(:\n")) == ""


def test_every_top_level_binding_shape_joins_its_group(tmp_path: pathlib.Path) -> None:
    """Annotated, chained and attribute assignments must not derail the walk.

    ``ALIAS = NAME = ...`` binds two names to one group; ``registry.slot = ...``
    binds none, and a walk that assumed every assignment owns a name would either
    crash or silently mis-group the file it is advising on.
    """
    path = _write(
        tmp_path,
        "import types\n"
        "\n"
        "registry = types.SimpleNamespace()\n"
        "registry.slot = 1\n"
        "\n"
        "ALPHA_LIMIT: int = 3\n"
        "\n"
        "\n"
        "def alpha() -> int:\n"
        "    return ALPHA_LIMIT\n"
        "\n"
        "\n"
        "def beta() -> int:\n"
        "    return 1\n"
        "\n"
        "\n"
        "BETA_ALIAS = BETA_NAME = beta\n",
    )
    seam = _proposed_seam(path)
    assert "ALPHA_LIMIT" in seam or "BETA_ALIAS" in seam
    groups = [
        set(members)
        for members, _ in _definition_components(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert {"ALPHA_LIMIT", "alpha"} in groups
    assert {"BETA_ALIAS", "BETA_NAME", "beta"} in groups


def test_a_long_group_lists_the_first_names_and_counts_the_rest(
    tmp_path: pathlib.Path,
) -> None:
    """Six coupled definitions must not print six names — the message stays a sentence."""
    body = "".join(
        f"def member_{index}() -> int:\n    return member_{index - 1}()\n\n\n"
        for index in range(1, 7)
    )
    path = _write(tmp_path, "def member_0() -> int:\n    return 0\n\n\n" + body + "LONE = 1\n")
    seam = _proposed_seam(path)
    assert "member_0, member_1, member_2, member_3, +3 more" in seam
    assert "LONE" not in seam


# --------------------------------------------------------------------------- #
# terp fmt
# --------------------------------------------------------------------------- #
def test_a_failed_git_call_reports_nothing_changed(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    """A non-zero ``git status`` means "no answer", never "format everything"."""

    class Refused:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Refused())
    assert changed_python_files(tmp_path) == []


def test_a_missing_git_binary_reports_nothing_changed(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise OSError("git is not installed")

    monkeypatch.setattr(subprocess, "run", refuse)
    assert changed_python_files(tmp_path) == []


def test_the_whole_tree_pass_invokes_the_formatter(tmp_path: pathlib.Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    class Result:
        returncode = 0

    def record(argv: list[str], **kwargs: object) -> Result:
        seen["argv"] = argv
        return Result()

    monkeypatch.setattr(subprocess, "run", record)
    assert run_fmt_command(root=tmp_path, changed=False, check=True) == 0
    assert seen["argv"][1:] == ["-m", "ruff", "format", "--check", "."]


def test_a_missing_ruff_is_a_named_failure_not_a_traceback(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise OSError("no ruff here")

    monkeypatch.setattr(subprocess, "run", refuse)
    assert run_fmt_command(root=tmp_path, changed=False) == 2
    assert "ruff is not installed" in capsys.readouterr().err


def test_cli_fmt_dispatch(tmp_path: pathlib.Path, monkeypatch, capsys) -> None:
    """The subcommand reaches the formatter and propagates its exit status."""
    monkeypatch.setattr("terp.cli.fmt.changed_python_files", lambda root: [])
    with pytest.raises(SystemExit) as exit_info:
        main(["fmt", "--root", str(tmp_path)])
    assert exit_info.value.code == 0
    assert "no changed Python files" in capsys.readouterr().out
