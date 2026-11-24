"""``TERP_EDGE_HOPS``: the hop a deploy tool's edge puts in front of the app (ADR 0220).

``SecurityConfig.trusted_proxy_hops`` counts the proxies the app's own code puts in front of
its api. A deploy tool that serves the app through an edge of its own adds a hop the source
cannot know of; it says so in ``TERP_EDGE_HOPS``, and ``create_app`` adds it to the declared
count, whatever the source says. A value other than 0 or 1 refuses the settings, and with
them the process; the name is the deploy tool's, so an app's manifest may not declare it.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from terp.cli.envschema import APP_ENV_SCHEMA_FILE, manifest_findings
from terp.core import (
    ControlPlane,
    ModuleSpec,
    Policy,
    SecurityConfig,
    client_ip,
    create_app,
    route_policy,
    settings,
)
from terp.core.config import Settings

#: The caller, as the edge records it, and an address a caller wrote in front of it.
CALLER = "203.0.113.7"
WRITTEN = "198.51.100.9"
#: The address a web unit's nginx appends: the edge's, as nginx sees it.
EDGE = "10.0.0.2"


def _app(declared: int) -> FastAPI:
    router = APIRouter()

    @router.get("/whoami")
    @route_policy(Policy.public(reason="a fixture that reports the caller it resolved"))
    def whoami(request: Request) -> dict:
        return {"caller": client_ip(request)}

    return create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.public(reason="probe route"))],
        control_plane=ControlPlane(security=SecurityConfig(trusted_proxy_hops=declared)),
    )


def _caller(app: FastAPI, forwarded: str) -> str:
    response = TestClient(app).get("/api/v1/probe/whoami", headers={"X-Forwarded-For": forwarded})
    assert response.status_code == 200, response.text
    return response.json()["caller"]


# --------------------------------------------------------------------------- #
# The setting
# --------------------------------------------------------------------------- #
def test_unset_is_no_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TERP_EDGE_HOPS", raising=False)
    assert Settings(_env_file=None).TERP_EDGE_HOPS == 0
    monkeypatch.setenv("TERP_EDGE_HOPS", "")
    assert Settings(_env_file=None).TERP_EDGE_HOPS == 0, "an empty value is unset"


@pytest.mark.parametrize(("value", "hops"), [("0", 0), ("1", 1), (" 1 ", 1)])
def test_the_values_a_deploy_tool_writes_are_read(
    monkeypatch: pytest.MonkeyPatch, value: str, hops: int
) -> None:
    monkeypatch.setenv("TERP_EDGE_HOPS", value)
    assert Settings(_env_file=None).TERP_EDGE_HOPS == hops


@pytest.mark.parametrize("value", ["2", "-1", "01", "1.0", "+1", "true", "one", "1,1"])
def test_any_other_value_refuses_the_settings(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A larger count reads past the edge's entry, to none or to one the caller wrote, so a
    value that is not 0 or 1 refuses, and says what the variable is for."""
    monkeypatch.setenv("TERP_EDGE_HOPS", value)
    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None)
    message = str(refused.value)
    assert "TERP_EDGE_HOPS is the proxy hop a deploy tool's edge puts in front" in message
    assert "0 or 1, or unset for none" in message
    assert "SecurityConfig.trusted_proxy_hops" in message, "the remedy for the app's own proxies"
    assert repr(value) not in message and f"input_value={value}" not in message


def test_a_boolean_is_not_a_count() -> None:
    with pytest.raises(ValidationError, match="TERP_EDGE_HOPS"):
        Settings(_env_file=None, TERP_EDGE_HOPS=True)
    assert Settings(_env_file=None, TERP_EDGE_HOPS=1).TERP_EDGE_HOPS == 1


def test_a_process_with_a_wrong_value_does_not_start(tmp_path: pathlib.Path) -> None:
    """The settings are read when ``terp.core`` is first imported: a wrong value stops the
    process there, before any app is composed, rather than serving on a count it guessed."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("TERP_EDGE")
    }
    environment["TERP_EDGE_HOPS"] = "2"
    completed = subprocess.run(  # fixed argv: this interpreter importing the framework
        [sys.executable, "-c", "import terp.core"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=120,
    )
    assert completed.returncode != 0
    assert "TERP_EDGE_HOPS is the proxy hop a deploy tool's edge" in completed.stderr + completed.stdout

    environment["TERP_EDGE_HOPS"] = "1"
    started = subprocess.run(  # fixed argv: the same import, with a value it reads
        [sys.executable, "-c", "from terp.core import settings; print(settings.TERP_EDGE_HOPS)"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=120,
    )
    assert started.returncode == 0, started.stderr
    assert started.stdout.strip() == "1"


# --------------------------------------------------------------------------- #
# The count create_app serves on
# --------------------------------------------------------------------------- #
def test_without_an_edge_the_declared_count_is_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 0)
    app = _app(declared=1)
    assert app.state.terp_control_plane.security.trusted_proxy_hops == 1
    assert _caller(app, f"{CALLER}, {EDGE}") == EDGE


def test_an_edge_in_front_of_an_api_unit_resolves_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """An api-only app declares no proxy of its own (ADR 0202). Behind the edge, the caller
    is the entry the edge wrote, not one the caller put in front of it."""
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    app = _app(declared=0)
    assert app.state.terp_control_plane.security.trusted_proxy_hops == 1
    assert _caller(app, CALLER) == CALLER
    assert _caller(app, f"{WRITTEN}, {CALLER}") == CALLER, "an entry the caller wrote is not taken"


def test_an_edge_in_front_of_a_web_unit_counts_both_hops(monkeypatch: pytest.MonkeyPatch) -> None:
    """The template's app counts its web unit's nginx; the edge stands in front of that. With
    the app's count alone, every caller would resolve to the edge's address."""
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    app = _app(declared=1)
    assert app.state.terp_control_plane.security.trusted_proxy_hops == 2
    assert _caller(app, f"{CALLER}, {EDGE}") == CALLER
    assert _caller(app, f"{WRITTEN}, {CALLER}, {EDGE}") == CALLER


def test_the_edge_is_added_whatever_the_source_declares(monkeypatch: pytest.MonkeyPatch) -> None:
    """The edge's hop is the deploy tool's fact, so no declaration takes it back: the count
    is the sum for every declared count."""
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    for declared in (0, 1, 3):
        assert _app(declared).state.terp_control_plane.security.trusted_proxy_hops == declared + 1


def test_the_boot_says_the_count_is_not_the_one_in_the_source(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    with caplog.at_level(logging.INFO, logger="terp.core"):
        _app(declared=1)
    said = [record.getMessage() for record in caplog.records if "TERP_EDGE_HOPS" in record.getMessage()]
    assert said == [
        "TERP_EDGE_HOPS adds the edge's 1 proxy hop to the 1 the control plane declares: "
        "the caller is entry 2 from the right of X-Forwarded-For"
    ]

    caplog.clear()
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 0)
    with caplog.at_level(logging.INFO, logger="terp.core"):
        _app(declared=1)
    assert "TERP_EDGE_HOPS" not in caplog.text


def test_the_undeclared_proxy_warning_names_the_edges_variable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An api-only app declares no proxy of its own, so behind an edge whose deploy tool set
    no hop the warning fires. It must send the reader to ``TERP_EDGE_HOPS`` for the edge,
    never to counting the edge in source, and it does not fire once the edge's hop is set."""
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 0)
    with caplog.at_level(logging.WARNING, logger="terp.core"):
        assert _caller(_app(declared=0), CALLER) == "testclient"
    warned = [r.getMessage() for r in caplog.records if "X-Forwarded-For" in r.getMessage()]
    assert len(warned) == 1
    assert "no TERP_EDGE_HOPS adds a hop" in warned[0]
    assert "A deploy tool's own edge is never declared there" in warned[0]

    caplog.clear()
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    with caplog.at_level(logging.WARNING, logger="terp.core"):
        assert _caller(_app(declared=0), CALLER) == CALLER
    assert "X-Forwarded-For" not in caplog.text


def test_a_count_past_the_edges_entry_falls_back_to_the_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An app that counts the edge in source as well reads past the edge's entry. Behind an
    edge that replaces the header there is nothing there, so every caller is the peer again:
    the shared bucket the edge's hop exists to end."""
    monkeypatch.setattr(settings, "TERP_EDGE_HOPS", 1)
    assert _caller(_app(declared=1), CALLER) == "testclient"


# --------------------------------------------------------------------------- #
# The name is the deploy tool's
# --------------------------------------------------------------------------- #
def test_an_apps_manifest_may_not_declare_the_edges_hop(tmp_path: pathlib.Path) -> None:
    """One owner per variable: an app that could set the edge's hop itself would have a
    second way to declare its proxies, and one a deploy tool also writes."""
    manifest = {
        "type": "object",
        "properties": {"TERP_EDGE_HOPS": {"type": "string", "format": "plain"}},
        "required": [],
    }
    (tmp_path / APP_ENV_SCHEMA_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    findings = manifest_findings(tmp_path)
    assert [(finding.subject, finding.detail) for finding in findings] == [
        ("TERP_EDGE_HOPS", "is platform-owned -- one owner per variable; remove it from the manifest")
    ]
