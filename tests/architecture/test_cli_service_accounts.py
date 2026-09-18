"""``terp service-account`` — the whole lifecycle of a machine credential (ADR 0088).

Issuing was the whole command for four releases. ``ServiceAccountService.revoke`` and
``ServiceAccountRead`` both existed and had no caller outside the framework's own tests,
so a credential could be issued and never administered: a leaked or stale secret had no
supported way to be turned off, and "is this integration still running?" — the question
``last_used_at`` is written to answer — had no surface that could ask it.

These run against a real store, like ``test_cli_users``: the value of an operator command
is that it works end to end against the audited service, and a stubbed one would prove
only that the arguments were passed along.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.core import settings  # noqa: E402
from terp.core._internal.engine import reset_engine  # noqa: E402

from terp.cli import main  # noqa: E402
from terp.cli.service_accounts import (  # noqa: E402
    create_service_account_command,
    render_service_accounts,
    revoke_service_account_command,
)

#: A synthetic app that registers the identity tables and creates the schema, so the
#: commands have a real store to act on (the shape `test_cli_users` uses).
_SA_APP = """\
from sqlmodel import SQLModel

from terp.core import create_app
from terp.core._internal.engine import get_engine

import terp.capabilities.identity.models  # noqa: F401  (register the tables)


def build():
    app = create_app([])
    SQLModel.metadata.create_all(get_engine())
    return app


app = build()
"""


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_path = (tmp_path / "terp.db").as_posix()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def app_module(tmp_path: pathlib.Path) -> str:
    (tmp_path / "sa_app.py").write_text(_SA_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("sa_app", None)
    return "sa_app"


def _create(app_module: str, name: str, *, role: str = "editor", days: int | None = 365) -> str:
    return create_service_account_command(
        name, role=role, app_ref=app_module, expires_in_days=days
    )


# --------------------------------------------------------------------------- #
# list — the question a renewal is planned from, and the one revocation needs
# --------------------------------------------------------------------------- #
def test_an_issued_credential_can_be_found_again(app_module: str) -> None:
    _create(app_module, "nightly-sync")
    rendered = render_service_accounts(app_ref=app_module)
    assert "nightly-sync" in rendered
    assert "never used" in rendered, (
        "last_used_at is what makes anyone willing to revoke, so it is on the line"
    )
    assert "expires" in rendered


def test_an_empty_store_says_so_rather_than_printing_a_bare_heading(app_module: str) -> None:
    assert "<none>" in render_service_accounts(app_ref=app_module)


def test_the_listing_never_shows_the_secret(app_module: str) -> None:
    """The DTO does the rendering precisely so this cannot regress.

    `ServiceAccountRead` is the safe face of the row — `hashed_secret` is not on it —
    and the command renders that rather than the ORM object.
    """
    created = _create(app_module, "nightly-sync")
    secret = created.split("client_secret:")[1].split("\n")[0].strip()
    rendered = render_service_accounts(app_ref=app_module)
    assert secret not in rendered
    assert "hashed_secret" not in render_service_accounts(app_ref=app_module, fmt="json")


def test_the_expiry_filter_is_the_renewal_question(app_module: str) -> None:
    """The default expiry is a year, so "what lapses soon" has to be askable early.

    An expiry that arrives unannounced is an integration that stops at 3am.
    """
    _create(app_module, "long-lived", days=365)
    _create(app_module, "about-to-lapse", days=10)
    rendered = render_service_accounts(app_ref=app_module, expiring_within_days=30)
    assert "about-to-lapse" in rendered
    assert "long-lived" not in rendered


def test_a_non_expiring_credential_is_shown_as_such(app_module: str) -> None:
    _create(app_module, "forever", days=None)
    assert "expires never" in render_service_accounts(app_ref=app_module)
    assert "forever" not in render_service_accounts(
        app_ref=app_module, expiring_within_days=3650
    ), "a credential with no end date can never be in a window"


def test_json_is_the_dto_a_tool_reads(app_module: str) -> None:
    _create(app_module, "nightly-sync")
    (document,) = json.loads(render_service_accounts(app_ref=app_module, fmt="json"))
    assert document["name"] == "nightly-sync"
    assert document["is_active"] is True
    assert "client_id" in document and "hashed_secret" not in document


def test_an_expired_credential_reads_as_expired(app_module: str) -> None:
    """Not just a date in the past: an operator scanning this is looking for a word."""
    _create(app_module, "lapsed", days=1)
    import sa_app  # noqa: F401 - already imported by the command above

    from sqlmodel import Session, select

    from terp.capabilities.identity.models import ServiceAccount
    from terp.core._internal.engine import get_engine

    with Session(get_engine()) as session:
        row = session.exec(select(ServiceAccount)).one()
        row.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)
        session.add(row)
        session.commit()
    assert "EXPIRED" in render_service_accounts(app_ref=app_module)


# --------------------------------------------------------------------------- #
# revoke — the security control that had no caller
# --------------------------------------------------------------------------- #
def test_revoking_by_name_deactivates_and_bumps_the_epoch(app_module: str) -> None:
    """The behaviour already existed and was already tested; the seam did not.

    `revoke()` bumps the token epoch and writes through the audited chokepoint, so
    outstanding access tokens stop working immediately. What was missing was any way to
    ask for it short of an app writing the call itself.
    """
    _create(app_module, "leaked")
    message = revoke_service_account_command("leaked", app_ref=app_module)
    assert "revoked" in message and "token epoch" in message

    from sqlmodel import Session, select

    from terp.capabilities.identity.models import ServiceAccount
    from terp.core._internal.engine import get_engine

    with Session(get_engine()) as session:
        row = session.exec(select(ServiceAccount)).one()
    assert row.is_active is False
    assert row.token_version == 1


def test_a_revoked_credential_leaves_the_live_listing_but_keeps_its_row(
    app_module: str,
) -> None:
    """The row stays for the audit trail; the default listing is the live set.

    A list that showed every credential ever issued would bury the ones an operator is
    actually checking.
    """
    _create(app_module, "leaked")
    revoke_service_account_command("leaked", app_ref=app_module)
    assert "leaked" not in render_service_accounts(app_ref=app_module)
    revoked = render_service_accounts(app_ref=app_module, include_revoked=True)
    assert "leaked" in revoked and "REVOKED" in revoked


def test_revoking_by_id_works_for_the_case_where_names_collide(app_module: str) -> None:
    """Nothing makes a service-account name unique, so the id has to remain addressable."""
    created = _create(app_module, "sync")
    account_id = created.split("(id ")[1].split(",")[0]
    assert "revoked" in revoke_service_account_command(account_id, app_ref=app_module)


def test_revoking_something_that_is_not_there_says_which_command_lists_them(
    app_module: str,
) -> None:
    with pytest.raises(SystemExit, match="no service account named 'ghost'"):
        revoke_service_account_command("ghost", app_ref=app_module)


def test_revoking_an_absent_id_is_refused_rather_than_silently_succeeding(
    app_module: str,
) -> None:
    with pytest.raises(SystemExit, match="no service account with id"):
        revoke_service_account_command(
            "11111111-1111-1111-1111-111111111111", app_ref=app_module
        )


# --------------------------------------------------------------------------- #
# the CLI itself — a command nothing routes to is a command that never runs
# --------------------------------------------------------------------------- #
def test_the_cli_dispatches_list_and_revoke(
    app_module: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _create(app_module, "nightly-sync")
    main(["service-account", "list", "--app", app_module, "--format", "json"])
    (document,) = json.loads(capsys.readouterr().out)
    assert document["name"] == "nightly-sync"

    main(["service-account", "revoke", "nightly-sync", "--app", app_module])
    assert "revoked" in capsys.readouterr().out


def test_there_is_deliberately_no_rotate() -> None:
    """The secret is write-once by decision, stated in two places.

    ADR 0088 Consequences: "there is no command to read a secret back — a lost secret is
    re-provisioned, not recovered." `ServiceAccountUpdate`: "Rotating a secret is a
    re-provision, not an edit … no field here could quietly replace the credential
    without the operator being handed the new one." A `rotate` verb would be the first
    thing to contradict both, so its absence is pinned rather than left to memory.
    """
    with pytest.raises(SystemExit):
        main(["service-account", "rotate", "anything"])

    from terp.capabilities.identity.schemas import ServiceAccountUpdate

    assert "hashed_secret" not in ServiceAccountUpdate.model_fields
    assert "client_secret" not in ServiceAccountUpdate.model_fields
