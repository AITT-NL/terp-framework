"""``terp secrets reseal``: the step that lets a decrypt fallback be dropped (ADR 0189).

A rotation puts the old key in ``SECRET_KEY_DECRYPT_FALLBACKS`` so every sealed value
still opens. The list may only come out of the environment once nothing needs it, and
"nothing needs it" has to be a fact the operator can read rather than a hope. These
tests are written from that seat:

* ``--check`` says what is still under a fallback and writes nothing;
* a run re-seals all of it under ``SECRET_KEY`` — app columns, webhook signing secrets
  and MFA enrolments alike — after which nothing remains under the fallback, and a
  second run writes nothing;
* it moves no ``updated_at``: a re-seal changes no value, only the key;
* a table that cannot be written rolls back whole, and the others keep their re-seal;
* a value rewritten by someone else mid-run is never overwritten;
* it refuses to run while a migration is pending.

The database is a RELATIVE SQLite path in the test's own directory: the migration guard
hands the URL to Alembic, whose config parser reads the percent-escapes of an absolute
Windows path as interpolation.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import secrets
import sys
import uuid
from collections.abc import Iterator
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, reseal_command  # noqa: E402

from terp.core import SealState, check_sealed_value, encrypt_config  # noqa: E402
from terp.core.config import settings  # noqa: E402

from terp.capabilities.mfa import seal_secret as seal_totp  # noqa: E402
from terp.capabilities.webhooks import seal_secret as seal_webhook  # noqa: E402

_OLD = secrets.token_urlsafe(32)
_NEW = secrets.token_urlsafe(32)

# Two app tables holding sealed config, so a per-table rollback has a neighbour to spare.
_APP = '''\
from sqlmodel import Field, SQLModel

from terp.core import BaseTable, create_app
from terp.core._internal.engine import get_engine


class ResealConnection(BaseTable, table=True):
    __tablename__ = "cli_reseal_connection"
    password: str = Field(max_length=512)
    host: str = Field(default="db.internal", max_length=64)


class ResealVault(BaseTable, table=True):
    __tablename__ = "cli_reseal_vault"
    token: str = Field(max_length=512)


def build():
    app = create_app([])
    SQLModel.metadata.create_all(get_engine())
    return app
'''


def _no_pending_migrations(engine: object) -> None:
    """A migrated database, without migrating one: the guard has its own test below."""


@pytest.fixture
def app(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """The app module, built against a fresh relative SQLite file, under the old key."""
    from terp.core._internal.engine import reset_engine

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///cli_reseal.db")
    monkeypatch.setattr(settings, "SECRET_KEY", _OLD)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    reset_engine()
    # Imported once per process: re-executing it would redeclare its tables on the
    # shared metadata. build() runs per test, which is what gives each a fresh database.
    (tmp_path / "cli_reseal_app.py").write_text(_APP, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("cli_reseal_app")
    module.build()
    yield module
    reset_engine()


def _rotate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", _NEW)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", [_OLD])
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [_OLD])


def _session() -> Session:
    from terp.core._internal.engine import get_engine

    return Session(get_engine())


def _seed(app: ModuleType) -> None:
    """Sealed values in every domain, under whatever key is current, plus plain ones."""
    from terp.capabilities.mfa.models import MfaEnrolment
    from terp.capabilities.webhooks.models import WebhookSubscription

    with _session() as session:
        session.add(app.ResealConnection(password=encrypt_config("dsn-password")))
        session.add(app.ResealVault(token=encrypt_config("vault-token")))
        session.add(
            WebhookSubscription(
                target_url="https://receiver.example/hook",
                secret=seal_webhook("hook-secret"),
                event="note.created",
                owner_id=uuid.uuid4(),
            )
        )
        session.add(MfaEnrolment(user_id=uuid.uuid4(), secret=seal_totp("JBSWY3DP")))
        session.commit()


def _stored() -> list[str]:
    """Every sealed value the database holds, in a stable order."""
    with _session() as session:
        rows = session.exec(
            text(
                "SELECT password FROM cli_reseal_connection "
                "UNION ALL SELECT token FROM cli_reseal_vault "
                "UNION ALL SELECT secret FROM webhook_subscription "
                "UNION ALL SELECT secret FROM mfa_enrolment"
            )
        ).all()
    return sorted(row[0] for row in rows)


def _run(*, check: bool = False, fmt: str = "text") -> tuple[int, str]:
    return reseal_command(
        app_ref="cli_reseal_app:build",
        check=check,
        fmt=fmt,
        migration_check=_no_pending_migrations,
    )


def test_check_names_what_still_needs_the_fallback_and_writes_nothing(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(app)
    _rotate(monkeypatch)
    before = _stored()
    status, report = _run(check=True)
    assert status == 1
    assert report.startswith("Checked; nothing was written:")
    assert "cli_reseal_connection.password" in report
    assert "webhook_subscription.secret" in report and "mfa_enrolment.secret" in report
    assert "4 value(s) still open only under SECRET_KEY_DECRYPT_FALLBACKS" in report
    assert _stored() == before


def test_reseal_moves_every_domain_to_the_new_key_and_a_second_run_writes_nothing(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(app)
    with _session() as session:
        stamped = session.exec(select(app.ResealConnection)).one().updated_at
    _rotate(monkeypatch)
    status, report = _run()
    assert status == 0, report
    assert report.startswith("Re-sealed under SECRET_KEY:")
    assert "SECRET_KEY_DECRYPT_FALLBACKS can come out of the environment" in report

    # Nothing remains under the fallback: every value opens under the new key alone.
    monkeypatch.setattr(settings, "SECRET_KEY_DECRYPT_FALLBACKS", [])
    assert {check_sealed_value(value).state for value in _stored()} == {SealState.CURRENT}
    # A re-seal changes no value, so it moves no updated_at.
    with _session() as session:
        assert session.exec(select(app.ResealConnection)).one().updated_at == stamped

    # Safe twice: nothing left to write, and the verdict is the same.
    after = _stored()
    status, report = _run(fmt="json")
    payload = json.loads(report)
    assert status == 0 and payload["clean"] is True and payload["wrote"] is True
    assert sum(column["resealed"] for column in payload["columns"]) == 0
    assert sum(column["current"] for column in payload["columns"]) == 4
    assert _stored() == after


def test_a_value_no_key_opens_is_reported_and_left_alone(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _session() as session:
        session.add(app.ResealVault(token="enc:v1:" + secrets.token_urlsafe(40)))
        session.commit()
    _rotate(monkeypatch)
    before = _stored()
    status, report = _run()
    assert status == 1
    assert "1 value(s) open under no configured key" in report
    assert _stored() == before


def test_a_table_that_cannot_be_written_rolls_back_whole_and_the_rest_keep_theirs(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(app)
    with _session() as session:
        session.exec(
            text(
                "CREATE TRIGGER cli_reseal_vault_frozen BEFORE UPDATE ON cli_reseal_vault "
                "BEGIN SELECT RAISE(ABORT, 'this table is append-only'); END"
            )
        )
        session.commit()
    _rotate(monkeypatch)
    status, report = _run()
    assert status == 1
    assert "Could not re-seal cli_reseal_vault (IntegrityError: this table is append-only)" in report
    with _session() as session:
        vault = session.exec(select(app.ResealVault)).one().token
        connection = session.exec(select(app.ResealConnection)).one().password
    assert check_sealed_value(vault).state is SealState.FALLBACK
    assert check_sealed_value(connection).state is SealState.CURRENT


def test_a_value_rewritten_mid_run_is_never_overwritten(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import terp.core

    _seed(app)
    _rotate(monkeypatch)
    with _session() as session:
        stale = session.exec(select(app.ResealVault)).one().token
    rewritten = encrypt_config("rotated-by-its-owner")  # what the running app writes meanwhile
    real_check = terp.core.check_sealed_value

    def racing_check(stored: str):
        # The app saves a new value after the re-seal read the row and before it writes.
        if stored == stale:
            with _session() as session:
                row = session.exec(select(app.ResealVault)).one()
                row.token = rewritten
                session.add(row)
                session.commit()
        return real_check(stored)

    monkeypatch.setattr(terp.core, "check_sealed_value", racing_check)
    status, report = _run()
    assert status == 1
    assert "1 value(s) changed while being re-sealed; run again" in report
    with _session() as session:
        assert session.exec(select(app.ResealVault)).one().token == rewritten


def test_it_refuses_to_run_while_a_migration_is_pending(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real guard: this database was built with create_all, so no package's history
    # has been applied and every installed capability reads as pending.
    _seed(app)
    _rotate(monkeypatch)
    before = _stored()
    status, report = reseal_command(app_ref="cli_reseal_app:build")
    assert status == 2
    assert "refuses to run while a migration is pending" in report
    assert "terp migrate upgrade" in report
    assert _stored() == before


def test_the_command_line_exits_with_the_verdict(
    app: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import terp.migrations.guard as guard

    monkeypatch.setattr(guard, "assert_migrations_current", lambda *args, **kwargs: None)
    _seed(app)
    _rotate(monkeypatch)
    with pytest.raises(SystemExit) as remains:
        main(["secrets", "reseal", "--app", "cli_reseal_app:build", "--check"])
    assert remains.value.code == 1
    main(["secrets", "reseal", "--app", "cli_reseal_app:build"])
    assert "Every sealed value opens under SECRET_KEY" in capsys.readouterr().out
