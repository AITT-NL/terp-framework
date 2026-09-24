"""``terp outbox`` — the surface that always exists.

The capability shipped no router and no command, so "nobody is draining this"
was reportable from nowhere. These assertions cover the operator's side of that:
the numbers, the reading of them, and the two ways the command can be asked for
something it cannot answer.

``dead-letters`` is the second half. The backlog counts what gave up; ``last_error``
says why, and had no reader in any shipped surface — so the platform recorded the
cause of every dead letter and could not be asked for it.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli.outbox import _duration, render_backlog, render_dead_letters  # noqa: E402

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


class _DeadLetter:
    """What ``terp.capabilities.outbox.dead_letters`` returns, as the CLI sees it."""

    def __init__(self, **fields: object) -> None:
        self.id = fields.get("id", "11111111-1111-1111-1111-111111111111")
        self.kind = fields.get("kind", "job")
        self.name = fields.get("name", "invoices.sync")
        self.attempts = fields.get("attempts", 5)
        self.created_at = fields.get("created_at", _NOW - timedelta(hours=2))
        self.dead_lettered_at = fields.get("dead_lettered_at", _NOW)
        self.last_error = fields.get("last_error", "ConnectionError: name or service not known")

    def as_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "name": self.name,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat(),
            "dead_lettered_at": (
                None if self.dead_lettered_at is None else self.dead_lettered_at.isoformat()
            ),
            "last_error": self.last_error,
        }


@pytest.fixture
def wired_dead_letters(monkeypatch: pytest.MonkeyPatch):
    """Same substitution as `wired`, for the dead-letter reader."""
    import terp.cli.outbox as outbox_module

    monkeypatch.setattr(outbox_module, "push_app_root", lambda root: None)
    monkeypatch.setattr(outbox_module, "load_app", lambda ref: None)
    calls: dict[str, object] = {}

    def _install(rows: list[_DeadLetter]) -> dict[str, object]:
        import types

        def _reader(session, *, name=None, since=None, limit=50):
            calls.update(name=name, since=since, limit=limit)
            return rows

        capability = types.ModuleType("terp.capabilities.outbox")
        capability.dead_letters = _reader  # type: ignore[attr-defined]
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
        return calls

    return _install


def test_a_dead_letter_is_named_and_its_reason_is_printed(wired_dead_letters) -> None:
    """The whole point: the count already existed, the cause did not.

    Everything an operator needs to act is on the entry — which job, how many attempts
    it burned, when it gave up, and the error it gave up on.
    """
    wired_dead_letters([_DeadLetter()])
    rendered = render_dead_letters()
    assert "job:invoices.sync" in rendered
    assert "attempts=5" in rendered
    assert "ConnectionError: name or service not known" in rendered
    assert "terminal" in rendered, "and it says the row will not come back on its own"


def test_a_row_with_no_recorded_error_says_so_rather_than_printing_nothing(
    wired_dead_letters,
) -> None:
    """A blank line reads as a rendering bug; `<no error recorded>` reads as a fact."""
    wired_dead_letters([_DeadLetter(last_error=None, dead_lettered_at=None)])
    rendered = render_dead_letters()
    assert "<no error recorded>" in rendered


def test_an_empty_window_explains_itself(wired_dead_letters) -> None:
    """The operator arrived here FROM a non-zero count, so an empty list needs a reason.

    Otherwise it reads as a broken command rather than as a filter that excluded
    everything — and the filter is the likely answer, because the backlog counts over
    all time and this does not.
    """
    wired_dead_letters([])
    rendered = render_dead_letters(since_days=1)
    assert "<none>" in rendered
    assert "older than the window" in rendered


def test_the_filters_reach_the_reader(wired_dead_letters) -> None:
    """A filter the command accepts and drops is worse than one it refuses."""
    calls = wired_dead_letters([])
    render_dead_letters(name="invoices.sync", since_days=7, limit=5)
    assert calls["name"] == "invoices.sync"
    assert calls["limit"] == 5
    assert calls["since"] is not None


def test_dead_letters_json_is_the_row_a_tool_reads(wired_dead_letters) -> None:
    wired_dead_letters([_DeadLetter()])
    (document,) = json.loads(render_dead_letters(fmt="json"))
    assert document["name"] == "invoices.sync"
    assert document["attempts"] == 5
    assert document["last_error"].startswith("ConnectionError")


def test_dead_letters_needs_the_capability_too(monkeypatch: pytest.MonkeyPatch) -> None:
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
        render_dead_letters()


def test_the_cli_dispatches_to_the_dead_letter_command(wired_dead_letters, capsys) -> None:
    from terp.cli import main

    wired_dead_letters([_DeadLetter()])
    main(["outbox", "dead-letters", "--format", "json"])
    (document,) = json.loads(capsys.readouterr().out)
    assert document["kind"] == "job"


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
