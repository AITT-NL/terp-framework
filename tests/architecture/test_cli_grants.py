"""``terp grant`` — make least privilege cheaper than widening a role.

Grants have existed since ADR 0013, but creating one required an admin token, the
subject's UUID and the exact permission string — three costs that together made
"just make it an admin" the rational choice. These tests pin the properties that
remove those costs: a subject is named the way operators name it, an unknown
permission is refused *with the catalog*, and the write goes through the audited
service rather than an HTTP round trip.
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

# An app that declares one permission and registers the identity + access tables, so
# the command has both a real catalog to validate against and a real store to write to.
_GRANT_APP = """\
from sqlmodel import SQLModel

from terp.core import ADMIN, VIEWER, ControlPlane, Permission, PermissionModel, create_app
from terp.core._internal.engine import get_engine

import terp.capabilities.access.models  # noqa: F401
import terp.capabilities.identity.models  # noqa: F401


def build():
    plane = ControlPlane(
        permissions=PermissionModel(
            permissions=[
                Permission("invoices.export", min_role=VIEWER),
                Permission("invoices.void", min_role=ADMIN),
            ]
        )
    )
    app = create_app([], control_plane=plane)
    SQLModel.metadata.create_all(get_engine())
    return app


app = build()
"""


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = (tmp_path / "terp.db").as_posix()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def app_module(tmp_path: pathlib.Path) -> str:
    (tmp_path / "grant_app.py").write_text(_GRANT_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("grant_app", None)
    return "grant_app"


def _run(app_module: str, tmp_path: pathlib.Path, *argv: str) -> None:
    main([*argv, "--app", f"{app_module}:build", "--app-root", str(tmp_path)])


def _make_service_account(tmp_path: pathlib.Path, app_module: str, name: str) -> str:
    main(
        [
            "service-account",
            "create",
            name,
            "--role",
            "viewer",
            "--app",
            f"{app_module}:build",
            "--app-root",
            str(tmp_path),
        ]
    )
    return name


# --------------------------------------------------------------------------- #
# Permission discovery — the half that stops people widening the role instead
# --------------------------------------------------------------------------- #
def test_an_unknown_permission_is_refused_and_lists_the_real_ones(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")
    with pytest.raises(SystemExit) as excinfo:
        _run(app_module, tmp_path, "grant", "add", account, "invoices.exprot")
    message = str(excinfo.value)
    assert "unknown permission" in message
    # The catalog itself is the point: "unknown permission" alone sends the reader
    # back to grepping the source, which is where they give up and grant admin.
    assert "invoices.export" in message
    assert "needs role viewer" in message


def test_a_permission_the_app_never_checks_is_not_stored(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")
    with pytest.raises(SystemExit):
        _run(app_module, tmp_path, "grant", "add", account, "invoices.delete_everything")
    out = _capture(app_module, tmp_path, "grant", "list", account)
    assert "holds no permission grants" in out


# --------------------------------------------------------------------------- #
# Subject resolution — operators have an email or a name, never a UUID
# --------------------------------------------------------------------------- #
def _capture(app_module: str, tmp_path: pathlib.Path, *argv: str) -> str:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _run(app_module, tmp_path, *argv)
    return buffer.getvalue()


def test_a_service_account_is_granted_by_its_name(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")

    out = _capture(app_module, tmp_path, "grant", "add", account, "invoices.export")

    assert "granted 'invoices.export'" in out
    assert "nightly-sync" in out


def test_a_user_is_granted_by_email(app_module: str, tmp_path: pathlib.Path) -> None:
    import os

    os.environ["TERP_USER_PASSWORD"] = "correct-horse-battery-9"  # noqa: S105
    try:
        main(
            [
                "user",
                "create",
                "ops@acme.test",
                "--role",
                "viewer",
                "--app",
                f"{app_module}:build",
                "--app-root",
                str(tmp_path),
            ]
        )
    finally:
        del os.environ["TERP_USER_PASSWORD"]

    out = _capture(
        app_module, tmp_path, "grant", "add", "ops@acme.test", "invoices.export"
    )
    assert "user 'ops@acme.test'" in out


def test_an_unknown_subject_fails_loudly(app_module: str, tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="no user with email"):
        _run(app_module, tmp_path, "grant", "add", "ghost@acme.test", "invoices.export")
    with pytest.raises(SystemExit, match="no service account named"):
        _run(app_module, tmp_path, "grant", "add", "ghost-job", "invoices.export")


# --------------------------------------------------------------------------- #
# list / revoke
# --------------------------------------------------------------------------- #
def test_granting_twice_is_idempotent(app_module: str, tmp_path: pathlib.Path) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")
    _run(app_module, tmp_path, "grant", "add", account, "invoices.export")
    _run(app_module, tmp_path, "grant", "add", account, "invoices.export")

    out = _capture(app_module, tmp_path, "grant", "list", account)
    assert out.count("invoices.export") == 1


def test_list_answers_why_can_it_do_that(app_module: str, tmp_path: pathlib.Path) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")
    assert "holds no permission grants" in _capture(
        app_module, tmp_path, "grant", "list", account
    )

    _run(app_module, tmp_path, "grant", "add", account, "invoices.export")

    assert "invoices.export" in _capture(app_module, tmp_path, "grant", "list", account)


def test_revoke_removes_the_grant_and_is_honest_when_there_was_none(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")
    assert "nothing to revoke" in _capture(
        app_module, tmp_path, "grant", "revoke", account, "invoices.export"
    )

    _run(app_module, tmp_path, "grant", "add", account, "invoices.export")
    assert "revoked 'invoices.export'" in _capture(
        app_module, tmp_path, "grant", "revoke", account, "invoices.export"
    )
    assert "holds no permission grants" in _capture(
        app_module, tmp_path, "grant", "list", account
    )


def _seed_stale_grant(app_module: str, tmp_path: pathlib.Path, permission: str):
    """Persist a grant for a permission the app does not declare, and return its subject.

    Loads the app first so the schema exists — the CLI does that itself, but these two
    cases have to write the row before the command runs.
    """
    import uuid

    from terp.capabilities.access import AccessService
    from terp.cli.grants import _load
    from terp.core.db import get_session

    _load(f"{app_module}:build", tmp_path)
    subject_id = uuid.uuid4()
    gen = get_session()
    session = next(gen)
    AccessService().grant(session, subject_id, permission)
    return subject_id


def test_revoke_can_clean_up_a_permission_the_app_no_longer_declares(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    # Revoke deliberately skips catalog validation: a stale grant is exactly the one
    # you most need to be able to remove, and it is unreachable if revoke insists the
    # permission still exists.
    subject_id = _seed_stale_grant(app_module, tmp_path, "invoices.retired")

    out = _capture(
        app_module, tmp_path, "grant", "revoke", str(subject_id), "invoices.retired"
    )
    assert "revoked 'invoices.retired'" in out


def test_list_flags_a_stale_grant_rather_than_hiding_it(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    subject_id = _seed_stale_grant(app_module, tmp_path, "invoices.retired")

    out = _capture(app_module, tmp_path, "grant", "list", str(subject_id))
    assert "invoices.retired" in out
    assert "stale" in out


def test_a_grant_below_the_permissions_minimum_role_warns_loudly(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    # The guard checks rank before grants, so this row can never fire. Storing it
    # silently would leave the operator believing the integration is authorized —
    # the same failure mode the unknown-permission path exists to prevent.
    account = _make_service_account(tmp_path, app_module, "nightly-sync")

    out = _capture(app_module, tmp_path, "grant", "add", account, "invoices.void")

    assert "granted 'invoices.void'" in out
    assert "WARNING" in out
    assert "requires role admin" in out
    assert "viewer" in out


def test_a_grant_at_or_above_the_minimum_role_does_not_warn(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _make_service_account(tmp_path, app_module, "nightly-sync")

    out = _capture(app_module, tmp_path, "grant", "add", account, "invoices.export")

    assert "WARNING" not in out


def test_an_app_without_a_control_plane_says_which_app_to_pass(
    tmp_path: pathlib.Path,
) -> None:
    # The catalog is read off the composed app, so pointing the command at something
    # that is merely a FastAPI app cannot be answered — and the answer has to name the
    # fix, because "no control plane" means nothing to someone who mistyped --app.
    (tmp_path / "bare_app.py").write_text(
        "from fastapi import FastAPI\n\n\ndef build():\n    return FastAPI()\n",
        encoding="utf-8",
    )
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("bare_app", None)

    with pytest.raises(SystemExit, match="exposes no control plane"):
        _run("bare_app", tmp_path, "grant", "add", "ops@acme.test", "invoices.export")


def test_a_refused_write_names_the_subject_it_was_for(
    app_module: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The store can refuse a write the CLI cannot foresee. The command must surface it
    # as a plain failure naming both permission and subject, not an unhandled traceback.
    from terp.capabilities.access import AccessService
    from terp.core import AppError

    account = _make_service_account(tmp_path, app_module, "nightly-sync")

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AppError("the access store is read-only")

    monkeypatch.setattr(AccessService, "grant", _refuse)

    with pytest.raises(SystemExit, match="could not grant 'invoices.export'") as exc:
        _run(app_module, tmp_path, "grant", "add", account, "invoices.export")
    assert "nightly-sync" in str(exc.value)
    assert "read-only" in str(exc.value)


def test_a_refused_provisioning_reaches_the_operator_as_a_plain_failure(
    app_module: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Provisioning writes through the audited service, which can refuse for reasons the
    # CLI cannot foresee. The operator gets the account name and the reason, not a
    # traceback out of a command that also prints a one-time secret.
    from terp.capabilities.identity import ServiceAccountService
    from terp.core import AppError

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AppError("the identity store is read-only")

    monkeypatch.setattr(ServiceAccountService, "provision", _refuse)

    with pytest.raises(SystemExit, match="could not create service account") as exc:
        _make_service_account(tmp_path, app_module, "nightly-sync")
    assert "read-only" in str(exc.value)


def test_role_rank_is_untouched_by_a_grant(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    # The whole point: an integration gets the one permission it needs *without*
    # climbing the role ladder. If granting silently bumped the rank we would have
    # rebuilt the problem we set out to remove.
    from terp.capabilities.identity import ServiceAccountService
    from terp.core.db import get_session

    account_name = _make_service_account(tmp_path, app_module, "nightly-sync")
    _run(app_module, tmp_path, "grant", "add", account_name, "invoices.export")

    gen = get_session()
    session = next(gen)
    account = ServiceAccountService().get_by_name(session, account_name)
    assert account is not None
    assert account.role == int(Roles.VIEWER)
