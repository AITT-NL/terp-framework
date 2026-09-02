"""``terp module-role`` — the first writer for per-module authority.

An operator command before a UI, on ADR 0089's pattern: the seam a fresh deployment needs is
the one that runs next to the database, because nobody has an admin session yet. These tests
pin the properties that make it safe to be that seam — every refusal names what *would* have
worked, and the refusals come from the capability rather than from the command, so an HTTP
surface added later cannot disagree with it.
"""

from __future__ import annotations

import contextlib
import io as _io
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.core import settings  # noqa: E402
from terp.core._internal.engine import reset_engine  # noqa: E402

from terp.cli import main  # noqa: E402

# An app with one assignable module, one that refuses assignment outright, one that stays
# silent, and a four-rung ladder — so every refusal has something real to be measured against.
_ROLE_APP = """\
from sqlmodel import SQLModel

from terp.core import (
    ADMIN,
    EDITOR,
    VIEWER,
    ControlPlane,
    ModuleAccess,
    ModuleSpec,
    PermissionModel,
    Policy,
    Role,
    create_app,
)
from terp.core._internal.engine import get_engine

import terp.capabilities.access.models  # noqa: F401
import terp.capabilities.identity.models  # noqa: F401

from terp.capabilities.access import resolve_module_rank


def build():
    plane = ControlPlane(
        permissions=PermissionModel(
            roles=(VIEWER, EDITOR, Role("approver", rank=25), ADMIN)
        )
    )
    modules = [
        ModuleSpec(
            name="invoices",
            policy=Policy.default(),
            access=ModuleAccess(label="Invoices", assignable=True),
        ),
        ModuleSpec(
            name="iam",
            policy=Policy.default(),
            access=ModuleAccess.platform_only(
                reason="administering accounts is the platform's own authority"
            ),
        ),
        ModuleSpec(name="ledger", policy=Policy.default()),
    ]
    app = create_app(
        modules, control_plane=plane, module_rank_resolver=resolve_module_rank
    )
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
    (tmp_path / "role_app.py").write_text(_ROLE_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop("role_app", None)
    return "role_app"


def _run(app_module: str, tmp_path: pathlib.Path, *argv: str) -> None:
    main([*argv, "--app", f"{app_module}:build", "--app-root", str(tmp_path)])


def _capture(app_module: str, tmp_path: pathlib.Path, *argv: str) -> str:
    buffer = _io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _run(app_module, tmp_path, *argv)
    return buffer.getvalue()


def _service_account(tmp_path: pathlib.Path, app_module: str, name: str) -> str:
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


def test_an_unknown_role_is_refused_and_lists_the_app_s_own_ladder(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    """Operators think in names, and the error has to teach the ladder.

    "unknown role" alone sends the reader back to the source, which is the moment they reach
    for a broader tier instead — the failure ADR 0089 was written about.
    """
    account = _service_account(tmp_path, app_module, "billing-sync")
    with pytest.raises(SystemExit) as excinfo:
        _run(app_module, tmp_path, "module-role", "add", account, "invoices", "editorr")
    message = str(excinfo.value)
    assert "unknown role 'editorr'" in message
    # The app's own ladder, including the rung it invented — not the packaged three.
    assert "approver  (rank 25)" in message


def test_a_platform_module_refuses_assignment_and_says_why(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    """Per-module `admin` in the wrong module is a way around the ladder, not a use of it.

    The reason travels with the refusal because the module declared one; a bare "not allowed"
    would leave an operator guessing whether it was a bug.
    """
    account = _service_account(tmp_path, app_module, "billing-sync")
    with pytest.raises(SystemExit) as excinfo:
        _run(app_module, tmp_path, "module-role", "add", account, "iam", "admin")
    assert "never per-module assignable" in str(excinfo.value)
    assert "the platform's own authority" in str(excinfo.value)


def test_a_module_that_never_opted_in_is_refused_and_names_the_ones_that_did(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _service_account(tmp_path, app_module, "billing-sync")
    with pytest.raises(SystemExit) as excinfo:
        _run(app_module, tmp_path, "module-role", "add", account, "ledger", "editor")
    message = str(excinfo.value)
    assert "has not opted into" in message
    assert "invoices" in message


def test_assigning_says_plainly_that_it_cannot_lower_authority(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    """The one thing an operator most needs told, because `max` is not obvious from outside.

    Someone assigning `viewer` in a module to a global admin has to know it will not demote
    them — otherwise the natural reading of "set the role in this module" is a mistake waiting
    to happen.
    """
    account = _service_account(tmp_path, app_module, "billing-sync")
    out = _capture(
        app_module, tmp_path, "module-role", "add", account, "invoices", "approver"
    )
    assert "assigned role 'approver' in module 'invoices'" in out
    assert "billing-sync" in out
    assert "cannot lower it" in out


def test_list_and_revoke_round_trip(app_module: str, tmp_path: pathlib.Path) -> None:
    account = _service_account(tmp_path, app_module, "billing-sync")
    assert "holds no per-module roles" in _capture(
        app_module, tmp_path, "module-role", "list", account
    )

    _run(app_module, tmp_path, "module-role", "add", account, "invoices", "editor")
    listed = _capture(app_module, tmp_path, "module-role", "list", account)
    assert "invoices: editor" in listed

    assert "revoked the role" in _capture(
        app_module, tmp_path, "module-role", "revoke", account, "invoices"
    )
    assert "nothing to revoke" in _capture(
        app_module, tmp_path, "module-role", "revoke", account, "invoices"
    )


def test_assigning_twice_updates_the_one_rung(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    account = _service_account(tmp_path, app_module, "billing-sync")
    _run(app_module, tmp_path, "module-role", "add", account, "invoices", "editor")
    _run(app_module, tmp_path, "module-role", "add", account, "invoices", "admin")
    listed = _capture(app_module, tmp_path, "module-role", "list", account)
    assert "invoices: admin" in listed
    assert listed.count("invoices") == 1


def test_revoke_can_clear_a_role_in_a_module_the_app_no_longer_supports(
    app_module: str, tmp_path: pathlib.Path
) -> None:
    """The row you most need to remove is the one the declarations no longer support.

    Written the way the grants suite writes its stale case: the assignment is created directly
    through the service, because the command itself would (correctly) refuse to create it.
    """
    import uuid

    from terp.capabilities.access import ModuleRoleService
    from terp.cli._subjects import load_app_for_cli
    from terp.core.db import get_session

    load_app_for_cli(f"{app_module}:build", tmp_path)
    subject = uuid.uuid4()
    session = next(get_session())
    # No explicit commit: the request session is write-guarded, and `assign` persists through
    # the audited chokepoint, which is what commits.
    ModuleRoleService().assign(session, subject, "retired", 20)

    listed = _capture(app_module, tmp_path, "module-role", "list", str(subject))
    assert "retired: editor" in listed
    assert "stale: this app no longer declares the module assignable" in listed

    assert "revoked the role" in _capture(
        app_module, tmp_path, "module-role", "revoke", str(subject), "retired"
    )
