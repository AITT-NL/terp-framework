"""``terp seed`` — run the app's declared seed routine (idempotent demo / bootstrap data).

Proves the orchestration: it builds the app (so ``create_app`` has configured the engine and
catalogs), resolves the ``seed(session)`` callable, and runs it in one write-guarded session —
failing closed on an unknown reference or when ``ENVIRONMENT=production`` (seed data is dev only).
The seed body itself is app-owned; here a synthetic seed stands in for it.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.core import settings  # noqa: E402
from terp.core._internal.engine import reset_engine  # noqa: E402

from terp.cli import main, run_seed_command  # noqa: E402

_SEED_APP = """\
from sqlmodel import SQLModel

from terp.core import create_app
from terp.core._internal.engine import get_engine

recorded: list[str] = []


def build():
    app = create_app([])
    SQLModel.metadata.create_all(get_engine())
    return app


def seed(session):
    recorded.append("ran")
    return "seeded 1 thing"


def seed_returns_none(session):
    recorded.append("none")
    return None


NOT_CALLABLE = 123

app = build()
"""


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{(tmp_path / 'terp.db').as_posix()}")
    reset_engine()
    yield
    reset_engine()


def _write_app(tmp_path: pathlib.Path) -> str:
    (tmp_path / "seed_app.py").write_text(_SEED_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("seed_app", None)
    return "seed_app"


def test_seed_runs_the_declared_callable(tmp_path: pathlib.Path) -> None:
    import importlib

    name = _write_app(tmp_path)
    message = run_seed_command(
        app_ref=f"{name}:app", app_root=tmp_path, seed_ref=f"{name}:seed", production=False
    )
    assert message == "seeded 1 thing"
    assert importlib.import_module(name).recorded == ["ran"]


def test_seed_defaults_a_summary_when_the_seed_returns_none(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    message = run_seed_command(
        app_ref=f"{name}:app",
        app_root=tmp_path,
        seed_ref=f"{name}:seed_returns_none",
        production=False,
    )
    assert message == "seeded"


def test_seed_defaults_production_from_settings(tmp_path: pathlib.Path) -> None:
    # production=None -> read settings.is_production (local in tests -> allowed to run).
    name = _write_app(tmp_path)
    message = run_seed_command(
        app_ref=f"{name}:app", app_root=tmp_path, seed_ref=f"{name}:seed", production=None
    )
    assert message == "seeded 1 thing"


def test_seed_refuses_to_run_in_production(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    with pytest.raises(SystemExit, match="refuses to run when ENVIRONMENT=production"):
        run_seed_command(
            app_ref=f"{name}:app", app_root=tmp_path, seed_ref=f"{name}:seed", production=True
        )


def test_seed_rejects_an_empty_seed_reference(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    with pytest.raises(SystemExit, match="not a valid"):
        run_seed_command(app_ref=f"{name}:app", app_root=tmp_path, seed_ref=":seed", production=False)


def test_seed_rejects_a_non_callable_seed(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    with pytest.raises(SystemExit, match="did not resolve to a callable"):
        run_seed_command(
            app_ref=f"{name}:app",
            app_root=tmp_path,
            seed_ref=f"{name}:NOT_CALLABLE",
            production=False,
        )


def test_cli_seed_dispatch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    name = _write_app(tmp_path)
    main(["seed", "--app", f"{name}:app", "--app-root", str(tmp_path), "--seed", f"{name}:seed"])
    assert "seeded 1 thing" in capsys.readouterr().out
