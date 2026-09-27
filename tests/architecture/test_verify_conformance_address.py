"""``terp verify --only conformance`` hands the suite the address this checkout publishes.

The conformance suite drives a stack that is already running, so the one thing it cannot
work out for itself is where that stack answers. The template's suite used to guess: its
Playwright config fell back to a literal port the workbench had stopped publishing when
host ports became per-checkout assignments (ADR 0134). Nothing set the real address, not
the generated app's CI and not this check, so a CI run drove an empty port and a developer's
run drove whatever else on the machine happened to listen there.

The address now has one source, read the way compose itself reads the web port, and the
template's config refuses to start without it. These tests hold the order of that lookup,
the refusal when there is no answer, and the one thing a refusal must never become: a
fallback to some port that might belong to somebody else.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli import main, verify  # noqa: E402
from terp.cli.dev import DEFAULT_WEB_PORT  # noqa: E402
from terp.cli.ports import render_block  # noqa: E402
from terp.cli.verify import (  # noqa: E402
    CONFORMANCE_BASE_URL_ENV,
    VerifyCheck,
    conformance_address,
)


@pytest.fixture(autouse=True)
def _no_address_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's shell may export any of these; the tests decide what is set."""
    for name in (CONFORMANCE_BASE_URL_ENV, "WEB_PORT", "UI_PORT"):
        monkeypatch.delenv(name, raising=False)


def _published(root: pathlib.Path, **values: int) -> pathlib.Path:
    """A checkout whose ``.env`` carries the block ``terp ports assign`` writes."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text(
        "SECRET_KEY=not-a-port\n\n" + render_block(values), encoding="utf-8"
    )
    return root


def _echo_the_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the suite for a process that prints the address it was handed."""
    monkeypatch.setattr(
        verify,
        "_CONFORMANCE",
        VerifyCheck(
            id="conformance",
            category="conformance",
            command=(
                f'"{pathlib.Path(sys.executable).as_posix()}" -c '
                f"\"import os; print('suite saw', os.environ['{CONFORMANCE_BASE_URL_ENV}'])\""
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# the lookup, in the order compose resolves the port
# --------------------------------------------------------------------------- #


def test_the_published_assignment_is_the_address(tmp_path: pathlib.Path) -> None:
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    assert conformance_address(root) == ("http://localhost:21107", "WEB_PORT from .env")


def test_the_process_environment_outranks_the_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose prefers a variable in its own environment over ``.env``, so the stack a
    workbench started with an exported port is on that port, whatever the file says."""
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    monkeypatch.setenv("WEB_PORT", "21342")
    assert conformance_address(root) == ("http://localhost:21342", "WEB_PORT from the environment")


def test_an_explicit_address_outranks_everything(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    monkeypatch.setenv("WEB_PORT", "21342")
    monkeypatch.setenv(CONFORMANCE_BASE_URL_ENV, "https://staging.example.test")
    assert conformance_address(root) == (
        "https://staging.example.test",
        f"{CONFORMANCE_BASE_URL_ENV} as given",
    )


def test_a_renamed_web_port_seam_is_the_one_read(tmp_path: pathlib.Path) -> None:
    """``workbench.json`` decides the variable's name, exactly as it does for ``terp ports``.
    A ``WEB_PORT`` in the same file is somebody else's leftover, not this app's port."""
    root = tmp_path / "app"
    root.mkdir()
    (root / ".env").write_text(
        "WEB_PORT=21999\n" + render_block({"UI_PORT": 21108, "BACKEND_PORT": 22108}),
        encoding="utf-8",
    )
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
    assert conformance_address(root) == ("http://localhost:21108", "UI_PORT from .env")


# --------------------------------------------------------------------------- #
# no answer is a refusal, never a guess
# --------------------------------------------------------------------------- #


def test_an_unassigned_checkout_has_no_address(tmp_path: pathlib.Path) -> None:
    """The case the old default existed for, and the reason it is gone: with no assignment
    this checkout's stack cannot be up, so any port named here is somebody else's."""
    root = tmp_path / "app"
    root.mkdir()
    url, why = conformance_address(root)
    assert url is None
    assert "no web port assigned" in why and "WEB_PORT" in why


def test_a_malformed_port_in_the_environment_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose would read this value and fail on it, so the file's value is not the answer."""
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    monkeypatch.setenv("WEB_PORT", "21o7")
    url, why = conformance_address(root)
    assert url is None
    assert "'21o7'" in why and "not a port" in why


def test_an_unreadable_declaration_is_not_read_as_the_default(tmp_path: pathlib.Path) -> None:
    """Broken JSON says nothing about which variable carries the port, and guessing
    ``WEB_PORT`` could hand the suite a value this app's compose file never reads."""
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    (root / "workbench.json").write_text("{ not json", encoding="utf-8")
    url, why = conformance_address(root)
    assert url is None
    assert "workbench.json cannot be read" in why


def test_an_unmanaged_app_names_its_own_address(tmp_path: pathlib.Path) -> None:
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    (root / "workbench.json").write_text(
        json.dumps({"unmanaged": True, "reason": "driven by a Makefile"}), encoding="utf-8"
    )
    url, why = conformance_address(root)
    assert url is None
    assert "unmanaged (driven by a Makefile)" in why


# --------------------------------------------------------------------------- #
# the check itself
# --------------------------------------------------------------------------- #


def test_the_check_refuses_before_the_suite_starts_and_names_both_fixes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "app"
    root.mkdir()
    _echo_the_address(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "release", "--only", "conformance", "--root", str(root)])
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "conformance has no stack to drive" in err
    assert "suite saw" not in err, "the suite must not run without an address"
    # Both ways out, because an agent reading this has to be able to act on it.
    assert "terp ports assign" in err
    assert f"{CONFORMANCE_BASE_URL_ENV}=http://localhost:{DEFAULT_WEB_PORT}" in err


def test_the_check_hands_the_suite_the_published_address(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Through the CLI, so the dispatch, the lookup and the environment overlay are one path:
    the suite must SEE the address, not merely have it computed on its behalf."""
    root = _published(tmp_path / "app", WEB_PORT=21107, API_PORT=22107)
    _echo_the_address(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "release",
                "--only",
                "conformance",
                "--root",
                str(root),
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 0
    document = json.loads(capsys.readouterr().out)
    (check,) = document["checks"]
    assert check["ok"] is True
    assert check["output_tail"].startswith(
        "conformance: driving http://localhost:21107 (WEB_PORT from .env)"
    )
    assert "suite saw http://localhost:21107" in check["output_tail"]


def test_the_manifest_states_the_assignment_as_a_precondition() -> None:
    """``requires`` is what a driving tool shows before it runs anything, so it has to
    name the step CI now takes and the escape a stack started some other way uses."""
    (check,) = [c for c in verify.PROFILES["release"] if c.id == "conformance"]
    assert check.runner == "conformance"
    assert "terp ports assign" in check.requires
    assert CONFORMANCE_BASE_URL_ENV in check.requires
