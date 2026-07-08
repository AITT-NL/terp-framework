"""``terp user create`` — bootstrap a user (especially the first admin) against the store.

The admin-only ``/users`` API cannot mint the *first* administrator, so this out-of-band seam
provisions through the audited ``UsersService`` chokepoint: strength is enforced, the write is
audited, and re-running for an existing email is a no-op. The password is read from the
environment or a prompt — never a CLI argument.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.core import Roles, settings  # noqa: E402
from terp.core._internal.engine import reset_engine  # noqa: E402

from terp.cli import main  # noqa: E402
from terp.cli.users import create_user_command, read_password, resolve_role  # noqa: E402

# A synthetic app that registers the identity `User` table and creates the schema, so the
# command has a real store to write to (mirrors the terp jobs CLI test's app module).
_USER_APP = """\
from sqlmodel import SQLModel

from terp.core import create_app
from terp.core._internal.engine import get_engine

import terp.capabilities.identity.models  # noqa: F401  (register the User table)


def build():
    app = create_app([])
    SQLModel.metadata.create_all(get_engine())
    return app


app = build()
"""

_STRONG_PASSWORD = "correct-horse-battery-9"  # noqa: S105 - test fixture, satisfies the policy


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the engine at a fresh per-test SQLite file, so each case starts empty."""
    db_path = (tmp_path / "terp.db").as_posix()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine()
    yield
    reset_engine()


def _write_app(tmp_path: pathlib.Path) -> str:
    (tmp_path / "user_app.py").write_text(_USER_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("user_app", None)
    return "user_app"


# --------------------------------------------------------------------------- #
# resolve_role
# --------------------------------------------------------------------------- #
def test_resolve_role_accepts_names() -> None:
    assert resolve_role("admin") == int(Roles.ADMIN)
    assert resolve_role("Editor") == int(Roles.EDITOR)
    assert resolve_role("viewer") == int(Roles.VIEWER)


def test_resolve_role_accepts_an_integer_rank() -> None:
    assert resolve_role("25") == 25


def test_resolve_role_rejects_an_unknown_name() -> None:
    with pytest.raises(SystemExit, match="viewer / editor / admin"):
        resolve_role("wizard")


def test_resolve_role_rejects_a_negative_rank() -> None:
    with pytest.raises(SystemExit, match=">= 0"):
        resolve_role("-1")


# --------------------------------------------------------------------------- #
# read_password
# --------------------------------------------------------------------------- #
def test_read_password_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERP_TESTPW", "from-env")
    assert read_password("TERP_TESTPW") == "from-env"


def test_read_password_prompts_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TERP_TESTPW", raising=False)
    monkeypatch.setattr("terp.cli.users.getpass.getpass", lambda prompt="": "typed")
    assert read_password("TERP_TESTPW") == "typed"


# --------------------------------------------------------------------------- #
# create_user_command
# --------------------------------------------------------------------------- #
def test_create_user_provisions_an_admin(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    message = create_user_command(
        "admin@acme.test",
        role="admin",
        app_ref=f"{name}:app",
        app_root=tmp_path,
        password_reader=lambda _env: _STRONG_PASSWORD,
    )
    assert "created user 'admin@acme.test'" in message
    assert f"role rank {int(Roles.ADMIN)}" in message


def test_create_user_is_idempotent(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    create_user_command(
        "dup@acme.test",
        app_ref=f"{name}:app",
        app_root=tmp_path,
        password_reader=lambda _env: _STRONG_PASSWORD,
    )
    again = create_user_command(
        "dup@acme.test",
        app_ref=f"{name}:app",
        app_root=tmp_path,
        password_reader=lambda _env: _STRONG_PASSWORD,
    )
    assert "already exists" in again


def test_create_user_rejects_a_weak_password(tmp_path: pathlib.Path) -> None:
    name = _write_app(tmp_path)
    with pytest.raises(SystemExit, match="could not create user"):
        create_user_command(
            "weak@acme.test",
            app_ref=f"{name}:app",
            app_root=tmp_path,
            password_reader=lambda _env: "short",
        )


def test_cli_user_create_dispatch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name = _write_app(tmp_path)
    monkeypatch.setenv("TERP_USER_PASSWORD", _STRONG_PASSWORD)
    main(
        [
            "user",
            "create",
            "cli@acme.test",
            "--role",
            "admin",
            "--app",
            f"{name}:app",
            "--app-root",
            str(tmp_path),
        ]
    )
    assert "created user 'cli@acme.test'" in capsys.readouterr().out
