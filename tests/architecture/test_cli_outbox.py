"""``terp outbox backlog`` — the surface that always exists.

The capability shipped no router and no command, so "nobody is draining this"
was reportable from nowhere. These assertions cover the operator's side of that:
the numbers, the reading of them, and the two ways the command can be asked for
something it cannot answer.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli.outbox import _duration, render_backlog  # noqa: E402

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _Backlog:
    """What ``terp.capabilities.outbox.backlog`` returns, as the CLI sees it."""

    def __init__(self, **fields: object) -> None:
        self.pending = fields.get("pending", 0)
        self.due = fields.get("due", 0)
        self.dead_lettered = fields.get("dead_lettered", 0)
        self.oldest_due_at = fields.get("oldest_due_at")
        self.oldest_due_age_seconds = fields.get("oldest_due_age_seconds")

    def as_dict(self) -> dict[str, object]:
        return {
            "pending": self.pending,
            "due": self.due,
            "dead_lettered": self.dead_lettered,
            "oldest_due_at": (
                None if self.oldest_due_at is None else self.oldest_due_at.isoformat()
            ),
            "oldest_due_age_seconds": self.oldest_due_age_seconds,
        }


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """Stand in for the app build and the session, so the command is what is tested.

    The command's own job is to load the app through the same seam `terp leases`
    uses and render what the capability reports; a real engine would test the
    capability again, which `test_outbox.py` already does.
    """
    import terp.cli.outbox as outbox_module

    monkeypatch.setattr(outbox_module, "push_app_root", lambda root: None)
    monkeypatch.setattr(outbox_module, "load_app", lambda ref: None)

    def _install(result: _Backlog) -> None:
        import types

        capability = types.ModuleType("terp.capabilities.outbox")
        capability.backlog = lambda session: result  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "terp.capabilities.outbox", capability)

        engine = types.ModuleType("terp.core._internal.engine")
        engine.get_engine = lambda: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "terp.core._internal.engine", engine)

        class _Session:
            def __init__(self, engine: object) -> None:
                pass

            def __enter__(self) -> object:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        sqlmodel = types.ModuleType("sqlmodel")
        sqlmodel.Session = _Session  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sqlmodel", sqlmodel)

    return _install


def test_an_empty_queue_says_nothing_is_due(wired) -> None:
    wired(_Backlog())
    rendered = render_backlog()
    assert "pending       0" in rendered
    assert "<nothing due>" in rendered
    assert "NO CONSUMER" not in rendered


def test_a_fresh_backlog_is_reported_without_alarm(wired) -> None:
    """Seconds of backlog is a queue being drained, not a queue that stopped."""
    wired(
        _Backlog(
            pending=3, due=1, oldest_due_at=_NOW, oldest_due_age_seconds=12.0
        )
    )
    rendered = render_backlog()
    assert "12s ago" in rendered
    assert "NO CONSUMER" not in rendered


def test_a_stalled_queue_is_interpreted_not_just_counted(wired) -> None:
    """An operator at 3am should not have to know what counts as normal. A worker
    claims due rows continuously, so minutes of untouched backlog reads as a
    consumer that is not running."""
    wired(
        _Backlog(
            pending=9,
            due=9,
            dead_lettered=2,
            oldest_due_at=_NOW - timedelta(hours=4),
            oldest_due_age_seconds=14_400.0,
        )
    )
    rendered = render_backlog()
    assert "4.0h ago" in rendered
    assert "NO CONSUMER" in rendered
    assert "terp jobs worker" in rendered, "and it names the thing to check"


def test_json_is_the_same_numbers_for_a_monitor(wired) -> None:
    wired(
        _Backlog(pending=2, due=1, dead_lettered=0, oldest_due_age_seconds=61.5)
    )
    document = json.loads(render_backlog(fmt="json"))
    assert document == {
        "pending": 2,
        "due": 1,
        "dead_lettered": 0,
        "oldest_due_at": None,
        "oldest_due_age_seconds": 61.5,
    }


def test_an_app_without_the_capability_is_told_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a traceback: the outbox is optional, and an app that never installed it
    is asking a reasonable question with a plain answer."""
    import builtins

    import terp.cli.outbox as outbox_module

    monkeypatch.setattr(outbox_module, "push_app_root", lambda root: None)
    monkeypatch.setattr(outbox_module, "load_app", lambda ref: None)
    real_import = builtins.__import__

    def _refuse(name: str, *args: object, **kwargs: object):
        if name == "terp.capabilities.outbox":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse)
    with pytest.raises(SystemExit, match="terp-cap-outbox is not installed"):
        render_backlog()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (12, "12s"),
        (89, "89s"),
        (200, "3m"),
        (5399, "90m"),
        (14_400, "4.0h"),
        (400_000, "4.6d"),
    ],
)
def test_an_age_is_shown_in_the_units_an_operator_thinks_in(
    seconds: float, expected: str
) -> None:
    assert _duration(seconds) == expected


def test_the_cli_dispatches_to_the_command(wired, capsys) -> None:
    """A command nothing routes to is a command that never runs."""
    from terp.cli import main

    wired(_Backlog(pending=1, due=1, oldest_due_age_seconds=5.0))
    main(["outbox", "backlog", "--format", "json"])
    assert json.loads(capsys.readouterr().out)["pending"] == 1
