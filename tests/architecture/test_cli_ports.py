"""``terp ports`` — the host ports a checkout owns, where every starter reads them.

The dev compose file used to default its published ports to a fixed pair, and
that pair was the first one a workbench hands out. So a start that did not come
from that workbench ran the same file with the names unset, landed on the
defaults, and — the compose project name being pinned — took over the same
containers as whichever checkout held the first pair.

These assertions hold the four properties that make the command a fix rather than
a second opinion: two checkouts never get one pair, assigning and publishing are
one act, an answer already published is *adopted* rather than replaced, and an
app that has opted out of being driven is left alone.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli import main  # noqa: E402
from terp.cli import ports as ports_module  # noqa: E402
from terp.cli.ports import (  # noqa: E402
    BLOCK_BEGIN,
    BLOCK_END,
    WEB_BASE,
    PortsError,
    claim_for,
    claims,
    declared_names,
    hide_from_git,
    home,
    is_unmanaged,
    ledger_path,
    merge_block,
    publish,
    published,
    render_block,
    run_ports_command,
)


def _checkout(root: pathlib.Path, *, env: str = "") -> pathlib.Path:
    """A plain directory standing in for a checkout, optionally with an ``.env``."""
    root.mkdir(parents=True, exist_ok=True)
    if env:
        (root / ".env").write_text(env, encoding="utf-8")
    return root


def _git_checkout(root: pathlib.Path) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    return root


def _dotenv(root: pathlib.Path) -> str:
    return (root / ".env").read_text(encoding="utf-8")


def _ports(root: pathlib.Path) -> dict:
    recorded = claim_for(json.loads(ledger_path().read_text(encoding="utf-8")), root)
    assert recorded is not None, f"no claim recorded for {root}"
    return recorded["ports"]


# --------------------------------------------------------------------------- #
# two checkouts never get one pair
# --------------------------------------------------------------------------- #


def test_two_checkouts_do_not_get_the_same_pair(tmp_path, capsys):
    """The defect, stated as a property: the second checkout must differ.

    Asserted as an exclusion rather than "the second one got 21101", because the
    numbers depend on what else is listening on the host — what must never happen
    is the two of them agreeing.
    """
    first = _checkout(tmp_path / "first")
    second = _checkout(tmp_path / "second")

    assert run_ports_command(action="assign", root=str(first)) == 0
    assert run_ports_command(action="assign", root=str(second)) == 0
    capsys.readouterr()

    mine, theirs = _ports(first), _ports(second)
    assert set(mine.values()).isdisjoint(set(theirs.values()))


def test_a_claim_held_by_another_checkout_is_skipped(tmp_path, capsys):
    """The ledger, not just the host probe, is what keeps a stopped app's pair.

    A probe alone would hand out the ports of every checkout that is not running
    right now, which is most of them — and the collision would arrive the next
    time that app started.
    """
    first = _checkout(tmp_path / "first")
    assert run_ports_command(action="assign", root=str(first)) == 0
    held = set(_ports(first).values())

    second = _checkout(tmp_path / "second")
    assert run_ports_command(action="assign", root=str(second)) == 0
    capsys.readouterr()

    assert set(_ports(second).values()).isdisjoint(held)


# --------------------------------------------------------------------------- #
# assigning and publishing are one act
# --------------------------------------------------------------------------- #


def test_assign_publishes_into_dotenv(tmp_path, capsys):
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    body = _dotenv(root)
    for name, value in _ports(root).items():
        assert f"{name}={value}" in body


def test_publishing_leaves_the_rest_of_dotenv_alone(tmp_path, capsys):
    """``.env`` is the app's file and holds its secrets; this owns one block."""
    root = _checkout(tmp_path / "app", env="SECRET_KEY=dev-secret\nDB_PORT=5432\n")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    body = _dotenv(root)
    assert "SECRET_KEY=dev-secret" in body
    assert "DB_PORT=5432" in body


def test_reassigning_the_same_checkout_changes_nothing(tmp_path, capsys):
    """Idempotent, and exactly one block — two would let Compose read the later."""
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    first = dict(_ports(root))

    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert _ports(root) == first
    assert _dotenv(root).count(BLOCK_BEGIN) == 1


# --------------------------------------------------------------------------- #
# an answer already published is adopted, not replaced
# --------------------------------------------------------------------------- #


def test_an_already_published_pair_is_adopted(tmp_path, capsys):
    """The property that makes this safe to run against a managed checkout.

    Something else assigned these ports and a stack may be up on them, so picking
    a second answer would move the ports of a running app. The published answer
    wins over a fresh pick.
    """
    root = _checkout(tmp_path / "app", env="WEB_PORT=29999\nAPI_PORT=29998\n")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert _ports(root) == {"WEB_PORT": 29999, "API_PORT": 29998}


def test_reassign_overrides_an_already_published_pair(tmp_path, capsys):
    """The other side of adoption: asking for a new pair has to actually give one."""
    root = _checkout(tmp_path / "app", env="WEB_PORT=29999\nAPI_PORT=29998\n")
    assert run_ports_command(action="assign", root=str(root), reassign=True) == 0
    capsys.readouterr()

    assigned = _ports(root)
    assert assigned["WEB_PORT"] != 29999
    assert assigned["WEB_PORT"] == WEB_BASE


def test_a_half_published_pair_is_not_adopted(tmp_path, capsys):
    """One name of the two is not an answer, and half-adopting it would keep a
    number whose partner was picked from a different generation."""
    root = _checkout(tmp_path / "app", env="WEB_PORT=29999\n")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert _ports(root)["WEB_PORT"] == WEB_BASE


# --------------------------------------------------------------------------- #
# the app's own declaration decides the names
# --------------------------------------------------------------------------- #


def test_a_renamed_host_port_env_is_honoured(tmp_path, capsys):
    """An app may name its ports whatever it likes as long as it says so."""
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "services": [
                    {"role": "web", "service": "web", "hostPortEnv": "UI_PORT"},
                    {"role": "api", "service": "api", "hostPortEnv": "BACKEND_PORT"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert set(_ports(root)) == {"UI_PORT", "BACKEND_PORT"}
    assert "WEB_PORT=" not in _dotenv(root)


def test_an_unmanaged_app_is_left_alone(tmp_path, capsys):
    """Opting out means the tool goes quiet, and the app keeps working.

    Guessing which names an app that drives its own loop uses would be this tool
    deciding something the app has just said is its own.
    """
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "driven by a Makefile"}),
        encoding="utf-8",
    )
    assert run_ports_command(action="assign", root=str(root)) == 0
    out = capsys.readouterr().out

    assert "unmanaged" in out
    assert not (root / ".env").exists()
    assert not ledger_path().exists()


# --------------------------------------------------------------------------- #
# refusals, removal, and a ledger that cannot be read
# --------------------------------------------------------------------------- #


def test_a_tracked_dotenv_refuses_to_be_written(tmp_path, capsys):
    """A machine's ports never reach an app's history, and the refusal says so."""
    root = _git_checkout(tmp_path / "app")
    (root / ".env").write_text("SECRET_KEY=dev\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True)

    assert run_ports_command(action="assign", root=str(root)) == 1
    out = capsys.readouterr().out

    assert "tracks .env" in out
    assert BLOCK_BEGIN not in _dotenv(root)
    # The claim is still recorded: the number is real and passable on a command
    # line even when this checkout is not a place it can be written down.
    assert _ports(root)


def test_release_drops_the_claim_and_the_block(tmp_path, capsys):
    root = _checkout(tmp_path / "app", env="SECRET_KEY=dev\n")
    assert run_ports_command(action="assign", root=str(root)) == 0
    assert BLOCK_BEGIN in _dotenv(root)

    assert run_ports_command(action="release", root=str(root)) == 0
    capsys.readouterr()

    body = _dotenv(root)
    assert BLOCK_BEGIN not in body
    assert "SECRET_KEY=dev" in body
    ledger = json.loads(ledger_path().read_text(encoding="utf-8"))
    assert claim_for(ledger, root) is None


def test_a_corrupt_ledger_is_not_fatal(tmp_path, capsys):
    """A file a developer did not know existed must not be able to stop them.

    The worst case of reading a broken ledger as empty is a second checkout
    picking a port the first holds, which the host probe still catches; the worst
    case of refusing is nobody able to start anything.
    """
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    ledger_path().write_text("{not json at all", encoding="utf-8")

    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert _ports(root)["WEB_PORT"] == WEB_BASE


def test_show_says_when_the_claim_is_not_published(tmp_path, capsys):
    """A recorded claim no starter can read is the defect, so it is reported."""
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    (root / ".env").unlink()
    capsys.readouterr()

    assert run_ports_command(action="show", root=str(root)) == 0
    assert "does not publish this claim" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# the ledger reader survives anything it finds in the file
# --------------------------------------------------------------------------- #


def test_home_defaults_under_the_user_when_terp_home_is_unset(monkeypatch):
    monkeypatch.delenv("TERP_HOME", raising=False)
    assert home().name == ".terp"


def test_home_ignores_a_blank_terp_home(monkeypatch):
    """An exported-but-empty variable is the shell's idea of unset, not a path."""
    monkeypatch.setenv("TERP_HOME", "   ")
    assert home().name == ".terp"


def test_a_ledger_that_is_not_an_object_is_read_as_empty(tmp_path, capsys):
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    ledger_path().write_text("[1, 2, 3]", encoding="utf-8")

    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()
    assert _ports(root)["WEB_PORT"] == WEB_BASE


@pytest.mark.parametrize(
    "claim",
    [
        "not-a-dict",
        {"ports": {"WEB_PORT": 1}},
        {"path": 7, "ports": {"WEB_PORT": 1}},
        {"path": "/p", "ports": "not-a-dict"},
        {"path": "/p", "ports": {"WEB_PORT": "not-an-int"}},
    ],
    ids=["scalar", "no-path", "path-not-str", "ports-not-dict", "port-not-int"],
)
def test_a_malformed_claim_is_ignored(claim):
    """Every claim is read defensively, because this file outlives its writer.

    Asserted as an exclusion: the malformed entry must be *absent* from the
    result, not merely tolerated alongside it.
    """
    assert claims({"claims": [claim]}) == []


def test_a_well_formed_claim_survives_the_filter():
    """The other side of the filter — otherwise it could reject everything."""
    claim = {"path": "/p", "ports": {"WEB_PORT": 1}}
    assert claims({"claims": [claim]}) == [claim]


# --------------------------------------------------------------------------- #
# reading what the app calls things
# --------------------------------------------------------------------------- #


def test_an_unmanaged_declaration_reports_itself(tmp_path):
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "a Makefile"}), encoding="utf-8"
    )
    assert is_unmanaged(root) == (True, "a Makefile")
    # And the names still answer, so a caller that asks anyway gets the defaults
    # rather than an exception.
    assert declared_names(root) == ("WEB_PORT", "API_PORT")


def test_a_declaration_without_port_names_falls_back_to_the_defaults(tmp_path):
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "services": [
                    {"role": "database", "service": "db"},
                    {"role": "web", "service": "web"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert declared_names(root) == ("WEB_PORT", "API_PORT")


def test_an_absent_dotenv_publishes_nothing(tmp_path):
    root = _checkout(tmp_path / "app")
    assert published(root, ("WEB_PORT",)) == {}


def test_comments_and_junk_in_dotenv_are_not_values(tmp_path):
    root = _checkout(
        tmp_path / "app",
        env="# WEB_PORT=1\nAPI_PORT=not-a-number\nNOISE\nWEB_PORT=7\n",
    )
    assert published(root, ("WEB_PORT", "API_PORT")) == {"WEB_PORT": 7}


def test_the_last_assignment_of_a_name_wins(tmp_path):
    """How Compose reads the file, so how this has to read it too."""
    root = _checkout(tmp_path / "app", env="WEB_PORT=1\nWEB_PORT=2\n")
    assert published(root, ("WEB_PORT",)) == {"WEB_PORT": 2}


# --------------------------------------------------------------------------- #
# the block
# --------------------------------------------------------------------------- #


def test_nothing_to_say_renders_no_block():
    assert render_block({}) == ""


def test_a_block_is_replaced_where_it_stands(tmp_path):
    """Appending instead would walk the block down the file on every run."""
    existing = f"A=1\n\n{BLOCK_BEGIN}\nWEB_PORT=1\n{BLOCK_END}\nZ=9\n"
    merged = merge_block(existing, render_block({"WEB_PORT": 2}))
    assert merged.index("A=1") < merged.index(BLOCK_BEGIN) < merged.index("Z=9")
    assert "WEB_PORT=2" in merged
    assert "WEB_PORT=1" not in merged


def test_an_unclosed_block_is_replaced_rather_than_doubled(tmp_path):
    """A truncated write leaves a fence with no close; a second block would let
    Compose read whichever came last."""
    existing = f"A=1\n{BLOCK_BEGIN}\nWEB_PORT=1\n"
    merged = merge_block(existing, render_block({"WEB_PORT": 2}))
    assert merged.count(BLOCK_BEGIN) == 1
    assert "WEB_PORT=1" not in merged


def test_a_crlf_file_keeps_its_line_endings(tmp_path):
    existing = "A=1\r\n"
    merged = merge_block(existing, render_block({"WEB_PORT": 2}))
    assert "\r\n" in merged
    assert "\n" not in merged.replace("\r\n", "")


def test_removing_a_block_from_a_file_that_has_none_changes_nothing():
    assert merge_block("A=1\n", "") == "A=1\n"


def test_a_block_is_the_whole_file_when_there_was_nothing_else():
    assert merge_block("", render_block({"WEB_PORT": 1})).startswith(BLOCK_BEGIN)


def test_removing_the_only_block_empties_the_file():
    existing = f"{BLOCK_BEGIN}\nWEB_PORT=1\n{BLOCK_END}\n"
    assert merge_block(existing, "") == ""


# --------------------------------------------------------------------------- #
# git, and the refusals
# --------------------------------------------------------------------------- #


def test_a_git_checkout_gets_a_local_exclude(tmp_path, capsys):
    """Written to .git/info/exclude, which is per-clone and uncommittable — the
    app's own .gitignore is the app's to write."""
    root = _git_checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    assert BLOCK_BEGIN in _dotenv(root)
    excluded = subprocess.run(
        ["git", "check-ignore", "-q", ".env"], cwd=root, check=False
    )
    assert excluded.returncode == 0


def test_an_already_ignored_dotenv_needs_no_exclude(tmp_path):
    root = _git_checkout(tmp_path / "app")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    assert hide_from_git(root) is True
    exclude = root / ".git" / "info" / "exclude"
    assert not exclude.exists() or ".env" not in exclude.read_text(encoding="utf-8")


def test_an_un_ignored_dotenv_refuses_to_be_written(tmp_path):
    """A negation in .gitignore beats the exclude, and a second exclude entry
    would not change that — so the write does not happen and says why."""
    root = _git_checkout(tmp_path / "app")
    (root / ".gitignore").write_text("!.env\n", encoding="utf-8")
    info = root / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "exclude").write_text(".env\n", encoding="utf-8")

    written, why_not = publish(root, {"WEB_PORT": 1})
    assert written is False
    assert "git would report" in why_not


def test_git_missing_altogether_is_not_a_crash(tmp_path, monkeypatch):
    """A machine with no git still has to be able to start an app."""
    root = _checkout(tmp_path / "app")

    def _no_git(*_args, **_kwargs):
        raise OSError("git is not installed")

    monkeypatch.setattr(ports_module.subprocess, "run", _no_git)
    written, why_not = publish(root, {"WEB_PORT": 1})
    assert written is True
    assert why_not == ""


def test_an_unwritable_dotenv_is_reported_not_raised(tmp_path, monkeypatch):
    root = _checkout(tmp_path / "app")

    def _refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(pathlib.Path, "write_text", _refuse)
    written, why_not = publish(root, {"WEB_PORT": 1})
    assert written is False
    assert "could not be written" in why_not


# --------------------------------------------------------------------------- #
# exhaustion, renames, and the remaining screens
# --------------------------------------------------------------------------- #


def test_no_free_pair_is_a_directive_refusal(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ports_module, "port_is_free", lambda _port: False)
    root = _checkout(tmp_path / "app")

    assert run_ports_command(action="assign", root=str(root)) == 1
    assert "No free port pair" in capsys.readouterr().out


def test_renaming_the_port_seams_keeps_the_numbers(tmp_path, capsys):
    """The pair is this checkout's; only the names it publishes them under move.

    Re-picking here would move the ports of a stack that may be up, for a change
    that was never about the numbers.
    """
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    before = sorted(_ports(root).values())

    (root / "workbench.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "services": [
                    {"role": "web", "service": "web", "hostPortEnv": "UI_PORT"},
                    {"role": "api", "service": "api", "hostPortEnv": "BACKEND_PORT"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()

    after = _ports(root)
    assert set(after) == {"UI_PORT", "BACKEND_PORT"}
    assert sorted(after.values()) == before


def test_list_says_so_when_the_ledger_is_empty(capsys):
    assert run_ports_command(action="list") == 0
    assert "No host-port claims recorded" in capsys.readouterr().out


def test_list_names_every_claim(tmp_path, capsys):
    first = _checkout(tmp_path / "first")
    second = _checkout(tmp_path / "second")
    run_ports_command(action="assign", root=str(first))
    run_ports_command(action="assign", root=str(second))
    capsys.readouterr()

    assert run_ports_command(action="list") == 0
    out = capsys.readouterr().out
    assert str(first.resolve()) in out
    assert str(second.resolve()) in out


def test_show_without_a_claim_points_at_assign(tmp_path, capsys):
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="show", root=str(root)) == 0
    out = capsys.readouterr().out
    assert "No host ports claimed" in out
    assert "terp ports assign" in out


def test_show_on_an_unmanaged_app_says_it_does_not_assign(tmp_path, capsys):
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "a Makefile"}), encoding="utf-8"
    )
    assert run_ports_command(action="show", root=str(root)) == 0
    assert "unmanaged" in capsys.readouterr().out


def test_show_prints_a_published_claim_without_complaint(tmp_path, capsys):
    root = _checkout(tmp_path / "app")
    run_ports_command(action="assign", root=str(root))
    capsys.readouterr()

    assert run_ports_command(action="show", root=str(root)) == 0
    out = capsys.readouterr().out
    assert "WEB_PORT=" in out
    assert "does not publish" not in out


def test_releasing_a_checkout_that_held_nothing_still_tidies_up(tmp_path, capsys):
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="release", root=str(root)) == 0
    assert "No host ports were claimed" in capsys.readouterr().out


def test_a_missing_directory_is_refused(tmp_path, capsys):
    assert run_ports_command(action="show", root=str(tmp_path / "nope")) == 2
    assert "No such directory" in capsys.readouterr().out


def test_an_unknown_action_is_refused(tmp_path, capsys):
    assert run_ports_command(action="fly", root=str(_checkout(tmp_path / "app"))) == 2
    assert "Unknown ports action" in capsys.readouterr().out


def test_the_cli_exposes_every_ports_subcommand(tmp_path, capsys):
    """Driven through ``main``, so the parser wiring and the dispatch are held too.

    A command that works when its function is called directly and not when it is
    typed is not a command, and nothing else in this file would notice.
    """
    root = _checkout(tmp_path / "app")
    for argv in (
        ["ports", "assign", "--root", str(root)],
        ["ports", "assign", "--root", str(root), "--reassign"],
        ["ports", "show", "--root", str(root)],
        ["ports", "list"],
        ["ports", "release", "--root", str(root)],
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code == 0, argv
    capsys.readouterr()


def test_a_port_something_else_holds_is_not_free(tmp_path):
    """The host probe is what skips the ports foreign applications already hold.

    Without it the collision surfaces much later as an opaque compose bind
    failure, which is the symptom this command exists to stop producing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        assert ports_module.port_is_free(taken) is False


def test_hiding_from_git_outside_a_checkout_reports_failure(tmp_path):
    """No repository means no exclude to write, and the caller has to be told —
    publishing anyway is how a machine's ports reach an app's history."""
    assert hide_from_git(_checkout(tmp_path / "app")) is False


def test_an_unwritable_exclude_reports_failure(tmp_path, monkeypatch):
    root = _git_checkout(tmp_path / "app")

    def _refuse(*_args, **_kwargs):
        raise OSError("read-only .git")

    monkeypatch.setattr(pathlib.Path, "write_text", _refuse)
    assert hide_from_git(root) is False


# --------------------------------------------------------------------------- #
# a declaration that cannot be read is not a declaration that is absent
# --------------------------------------------------------------------------- #


def _broken_declaration(root: pathlib.Path, body: str) -> pathlib.Path:
    (root / "workbench.json").write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "body",
    [
        "{not json",
        '["an array, not an object"]',
        '{"schemaVersion": 99}',
        '{"unmanaged": true}',
    ],
    ids=["invalid-json", "not-an-object", "unknown-version", "escape-without-reason"],
)
def test_an_unreadable_declaration_refuses_to_assign(body, tmp_path, capsys):
    """``workbench.load`` answers ``(None, findings)`` for a declaration it cannot
    *read*, which at the type level is the same answer as "this app has none".

    Treating those two the same is how an app that renamed its port seam and then
    broke its JSON gets ``WEB_PORT`` published — a name its compose file never
    reads, so the stack binds the compose default and takes over another
    checkout's containers. That is the failure this command exists to remove,
    reintroduced by guessing, so it refuses instead.

    ``{"unmanaged": true}`` with no reason is in this list on purpose: an escape
    nobody can review is not an escape, and it must not read as one.
    """
    root = _broken_declaration(_checkout(tmp_path / "app"), body)

    assert run_ports_command(action="assign", root=str(root)) == 1
    out = capsys.readouterr().out

    assert "workbench.json" in out
    assert "terp verify --only workbench" in out
    assert not (root / ".env").exists()
    assert not ledger_path().exists()


def test_an_unreadable_declaration_refuses_to_show(tmp_path, capsys):
    root = _broken_declaration(_checkout(tmp_path / "app"), "{not json")
    assert run_ports_command(action="show", root=str(root)) == 1
    assert "cannot be read" in capsys.readouterr().out


def test_assign_refuses_an_unmanaged_app_on_its_own(tmp_path):
    """The guard lives in `assign`, not only in the screen above it, so no caller
    can reach the half that would guess."""
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "a Makefile"}), encoding="utf-8"
    )
    with pytest.raises(PortsError, match="unmanaged"):
        ports_module.assign(root)


def test_seams_report_their_problems_rather_than_a_guess(tmp_path):
    seams = ports_module.read_seams(_broken_declaration(_checkout(tmp_path / "a"), "{"))
    assert seams.problems
    assert seams.unmanaged is False


# --------------------------------------------------------------------------- #
# the ledger is not rewritten by a reader that cannot model it
# --------------------------------------------------------------------------- #


def test_a_newer_ledger_is_read_but_never_rewritten(tmp_path, capsys):
    """Every write replaces the claim list wholesale and the reader drops what it
    cannot model, so an older terp rewriting a newer ledger would delete claims
    it merely failed to understand — and then hand out ports they hold."""
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    ledger_path().write_text(
        json.dumps(
            {
                "schemaVersion": ports_module.SCHEMA_VERSION + 1,
                "claims": [{"path": "/elsewhere", "ports": {"WEB_PORT": 21100}}],
            }
        ),
        encoding="utf-8",
    )

    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 1
    assert "newer terp" in capsys.readouterr().out
    # And the file it refused to own is still exactly as it was.
    assert json.loads(ledger_path().read_text(encoding="utf-8"))["claims"] == [
        {"path": "/elsewhere", "ports": {"WEB_PORT": 21100}}
    ]


def test_releasing_against_a_newer_ledger_also_refuses(tmp_path):
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    ledger_path().write_text(
        json.dumps({"schemaVersion": ports_module.SCHEMA_VERSION + 1, "claims": []}),
        encoding="utf-8",
    )
    with pytest.raises(PortsError, match="newer terp"):
        ports_module.release(_checkout(tmp_path / "app"))


# --------------------------------------------------------------------------- #
# two writers over one ledger
# --------------------------------------------------------------------------- #


def test_concurrent_assigns_do_not_lose_a_claim(tmp_path, capsys, monkeypatch):
    """The read-compute-replace window, which two conversations hit routinely.

    ``_store`` is slowed so the two calls reliably overlap; without the lock the
    second write is computed from a ledger that predates the first and one claim
    is dropped — and a dropped claim is a port handed to a second checkout.
    """
    real_store = ports_module._store

    def _slow_store(path, data):
        time.sleep(0.15)
        real_store(path, data)

    monkeypatch.setattr(ports_module, "_store", _slow_store)

    roots = [_checkout(tmp_path / f"app{n}") for n in range(2)]
    errors: list[BaseException] = []

    def _run(root):
        try:
            ports_module.assign(root)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(root,)) for root in roots]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    capsys.readouterr()

    assert errors == []
    ledger = json.loads(ledger_path().read_text(encoding="utf-8"))
    held = [claim_for(ledger, root) for root in roots]
    assert all(claim is not None for claim in held), ledger
    first, second = (set(claim["ports"].values()) for claim in held)
    assert first.isdisjoint(second)


def test_a_stale_lock_is_broken_rather_than_waited_on(tmp_path, capsys):
    """A crashed process must not leave a machine unable to assign a port."""
    lock = ledger_path().with_name(ledger_path().name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))

    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="assign", root=str(root)) == 0
    capsys.readouterr()
    assert _ports(root)["WEB_PORT"] == WEB_BASE


def test_a_held_lock_delays_but_does_not_block_forever(tmp_path):
    """The timeout is deliberate: a start that waits forever is worse than one
    that proceeds on a ledger it could not lock."""
    lock = ledger_path().with_name(ledger_path().name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")

    started = time.monotonic()
    with ports_module._ledger_lock(timeout=0.2, stale_after=3600):
        pass
    assert time.monotonic() - started >= 0.2


def test_a_lock_that_has_gone_reads_as_age_zero_not_ancient(tmp_path):
    """Released, not stale. Calling it ancient would break a lock the next
    caller is about to take legitimately."""
    assert ports_module._lock_age(tmp_path / "never-existed.lock") == 0.0


def test_a_home_that_cannot_hold_a_lock_still_yields(tmp_path, monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise OSError("no locks here")

    monkeypatch.setattr(ports_module.os, "open", _refuse)
    entered = False
    with ports_module._ledger_lock(timeout=0.01):
        entered = True
    assert entered is True


# --------------------------------------------------------------------------- #
# the start-path entry point never raises
# --------------------------------------------------------------------------- #


def test_ensure_assigned_claims_and_publishes_and_says_so(tmp_path):
    root = _checkout(tmp_path / "app")
    values, note = ports_module.ensure_assigned(root)

    assert values == _ports(root)
    assert f"WEB_PORT={values['WEB_PORT']}" in note
    assert BLOCK_BEGIN in _dotenv(root)


def test_ensure_assigned_is_quiet_when_nothing_changed(tmp_path):
    """A note on every start would be noise; a note when a pair was claimed is
    the one line worth printing."""
    root = _checkout(tmp_path / "app")
    ports_module.ensure_assigned(root)
    _, note = ports_module.ensure_assigned(root)
    assert note == ""


def test_ensure_assigned_says_nothing_at_all_for_an_unmanaged_app(tmp_path):
    """It said its loop is its own. A line about ports it does not use would be
    this tool insisting anyway."""
    root = _checkout(tmp_path / "app")
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "a Makefile"}), encoding="utf-8"
    )
    assert ports_module.ensure_assigned(root) == ({}, "")


def test_ensure_assigned_reports_a_broken_declaration_instead_of_raising(tmp_path):
    """The whole reason this wrapper exists: a start must not die because the
    assignment could not be arranged."""
    root = _broken_declaration(_checkout(tmp_path / "app"), "{not json")
    values, note = ports_module.ensure_assigned(root)
    assert values == {}
    assert "workbench.json" in note


def test_ensure_assigned_reports_a_refused_publication(tmp_path):
    root = _git_checkout(tmp_path / "app")
    (root / ".env").write_text("SECRET_KEY=dev\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True)

    values, note = ports_module.ensure_assigned(root)
    assert values  # the claim is real and passable on a command line
    assert "not published" in note


# --------------------------------------------------------------------------- #
# release leaves nothing behind
# --------------------------------------------------------------------------- #


def test_release_does_not_create_a_dotenv_that_never_existed(tmp_path, capsys):
    """Tidying up is not the same as leaving something behind."""
    root = _checkout(tmp_path / "app")
    assert run_ports_command(action="release", root=str(root)) == 0
    capsys.readouterr()
    assert not (root / ".env").exists()


def test_a_ledger_that_cannot_be_written_is_a_directive_error(tmp_path, monkeypatch):
    """The ledger is the thing that keeps two checkouts apart, so a machine that
    cannot hold one has to say so rather than hand out a pair it will forget."""
    root = _checkout(tmp_path / "app")

    def _refuse(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", _refuse)
    with pytest.raises(PortsError, match="port ledger"):
        ports_module.assign(root)
