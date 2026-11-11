"""The app compares the routes it will serve with its record when it starts (ADR 0212).

The check before release composes the app and compares it with ``authz-surface.json``, so
code written to fool it can show that check a narrower app than the one it serves. These
tests pin the second half: ``create_app`` reduces the routes it just composed with the same
function and compares them with the same record, and outside ``ENVIRONMENT=local`` an app
that does not serve what its record says does not start.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import terp.cli.verify as verify_module
from terp.cli.access import build_access_graph_for_app
from terp.cli.authz_surface import check
from terp.core import ADMIN, BootError, ControlPlane, ModuleSpec, Policy, create_app
from terp.core.authz_surface import ADOPT_HINT, SURFACE_ARTIFACT, render_authz_surface
from terp.core.config import settings
from terp.core.routing import route_policy

#: What the deceptive app reads to tell that it is being inspected. Any signal does: the
#: command line, an environment variable, a database that is not there.
_INSPECTED = "TERP_TEST_BEING_INSPECTED"


def _nothing() -> dict:
    return {}


def _router(*extra: str) -> APIRouter:
    router = APIRouter()

    @router.get("/thing")
    def read_thing() -> dict:
        return {}

    for name in extra:
        router.add_api_route(f"/{name}", _nothing, methods=["GET"], name=name)
    return router


def _app(*extra: str, policy: Policy | None = None):
    return create_app(
        [ModuleSpec(name="probe", router=_router(*extra), policy=policy or Policy.default())],
        control_plane=ControlPlane(),
    )


def _deceptive_app():
    """Serves `/export` to anyone, and leaves it out while it is being inspected."""
    import os

    router = _router()
    if not os.environ.get(_INSPECTED):

        @router.get("/export")
        @route_policy(Policy.public(reason="left out wherever the check runs"))
        def export() -> dict:
            return {"rows": "all of them"}

    return create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.default())],
        control_plane=ControlPlane(),
    )


@pytest.fixture
def project(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A working directory of its own, as a project root or an image's ``/srv`` is."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _record(project: pathlib.Path, *extra: str, policy: Policy | None = None) -> None:
    """Write the record of the plain app, as the README's first command does."""
    (project / SURFACE_ARTIFACT).write_text(
        render_authz_surface(build_access_graph_for_app(_app(*extra, policy=policy))),
        encoding="utf-8",
    )


def _deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- #
# the proof: an app that shows the check less than it serves does not start
# --------------------------------------------------------------------------- #
def test_an_app_that_hides_a_route_from_the_check_passes_it_and_then_refuses_to_start(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap this half closes, end to end.

    While it is inspected the app leaves its public export out, so the record is written
    without it and the check before release passes: nothing it can see differs. Deployed,
    the same code composes the route, and the app refuses to start on it.
    """
    monkeypatch.setenv(_INSPECTED, "1")
    (project / SURFACE_ARTIFACT).write_text(
        render_authz_surface(build_access_graph_for_app(_deceptive_app())), encoding="utf-8"
    )
    monkeypatch.setattr(
        verify_module, "_DEFAULT_APP_REF", "tests.architecture.test_startup_surface:_deceptive_app"
    )
    exit_code, output = check(project, verify_module._DEFAULT_APP_REF, note_prefix="")
    assert (exit_code, output) == (0, f"{SURFACE_ARTIFACT} matches the composed authorization surface")

    monkeypatch.delenv(_INSPECTED)
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _deceptive_app()
    message = str(refused.value)
    assert f"this app does not serve what {SURFACE_ARTIFACT} records: 1 difference(s):" in message
    assert "  - widens: GET /api/v1/probe/export: NEW endpoint, requirement 'public'" in message
    # It names both ways out, and neither is "regenerate until it is quiet".
    assert ADOPT_HINT in message
    assert "a route or a module added under a condition" in message


def test_the_same_app_is_served_where_nothing_compares_it(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the proof above: with no record beside it, the route is served.

    So the refusal there is the comparison's, not something else about the app.
    """
    _deployed(monkeypatch)
    assert TestClient(_deceptive_app()).get("/api/v1/probe/export").json() == {"rows": "all of them"}


# --------------------------------------------------------------------------- #
# what starts, and what it says
# --------------------------------------------------------------------------- #
def test_an_app_that_serves_its_record_starts_and_says_so(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _record(project)
    _deployed(monkeypatch)
    with caplog.at_level("INFO", logger="terp.core"):
        app = _app()
    assert f"{SURFACE_ARTIFACT} matches the routes this app serves" in _logged(caplog)
    assert TestClient(app).get("/health/live").status_code == 200


def test_an_app_without_a_record_starts_and_says_it_was_not_compared(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Adoption stays opt-in, as it is for the check before release (ADR 0209).

    What it may not do is read as checked: a deployed process with no record says so.
    """
    _deployed(monkeypatch)
    with caplog.at_level("INFO", logger="terp.core"):
        _app()
    logged = _logged(caplog)
    assert f"no {SURFACE_ARTIFACT} in the working directory" in logged
    assert "were not compared with a record" in logged
    assert ADOPT_HINT in logged


def test_in_development_an_app_without_a_record_says_nothing(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="terp.core"):
        _app()
    assert SURFACE_ARTIFACT not in _logged(caplog)


def test_in_development_a_matching_record_says_nothing(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    _record(project)
    with caplog.at_level("INFO", logger="terp.core"):
        _app()
    assert SURFACE_ARTIFACT not in _logged(caplog)


# --------------------------------------------------------------------------- #
# every difference refuses, in either direction
# --------------------------------------------------------------------------- #
def test_an_app_that_serves_less_than_its_record_refuses_too(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A narrowing is a difference as well: the record no longer says what is served."""
    _record(project, "report")
    _deployed(monkeypatch)
    with pytest.raises(BootError, match="narrows: GET /api/v1/probe/report: gone from the surface"):
        _app()


def test_a_changed_policy_refuses(project: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same routes under a lower floor: no route is new, and who reaches them is."""
    _record(project, policy=Policy.tiers(read=ADMIN, write=ADMIN))
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app()
    message = str(refused.value)
    assert "widens: GET /api/v1/probe/thing: requirement 'role:admin' -> 'role:viewer'" in message
    assert "widens: module probe: policy" in message


def test_a_refusal_names_the_first_few_differences_and_counts_the_rest(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A boot error is read in a log, so it names five and says where the rest are."""
    _record(project)
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app("a", "b", "c", "d", "e", "f", "g")
    message = str(refused.value)
    assert "7 difference(s)" in message
    assert message.count("NEW endpoint") == 5
    assert "... and 2 more (`terp verify --only authz-surface` lists every one)" in message


def test_in_development_a_difference_is_a_warning_and_the_app_starts(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A developer who adds a route serves it at once, and is told what the record lacks."""
    _record(project)
    with caplog.at_level("WARNING", logger="terp.core"):
        app = _app("report")
    assert TestClient(app).get("/health/live").status_code == 200
    logged = _logged(caplog)
    assert "widens: GET /api/v1/probe/report: NEW endpoint" in logged
    assert "Outside ENVIRONMENT=local this app refuses to start on this (ADR 0212)." in logged


# --------------------------------------------------------------------------- #
# a record that cannot be read is not an absent one
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "Expecting value"),
        ("{", "Expecting property name"),
        ("[]", "it is not a JSON object"),
        ('{"modules": [3]}', "it is not a surface this version of the framework reads: AttributeError"),
        ('{"modules": [{"name": "probe", "endpoints": [{}]}]}', "reads: KeyError: 'path'"),
    ],
)
def test_a_record_that_cannot_be_read_refuses(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch, text: str, reason: str
) -> None:
    (project / SURFACE_ARTIFACT).write_text(text, encoding="utf-8")
    _deployed(monkeypatch)
    with pytest.raises(BootError) as refused:
        _app()
    message = str(refused.value)
    assert f"{SURFACE_ARTIFACT} cannot be read (" in message
    assert reason in message
    assert "Restore the committed file from version control" in message


def test_a_record_that_is_not_text_refuses(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / SURFACE_ARTIFACT).write_bytes(b"\xff\xfe\x00")
    _deployed(monkeypatch)
    with pytest.raises(BootError, match="cannot be read"):
        _app()


def test_in_development_an_empty_record_is_the_one_being_written(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`terp inspect access ... > authz-surface.json` empties the file before it composes.

    The shell opens the redirect first, so the command that writes the record always meets
    an empty one. Warning about it would warn on every write of the record.
    """
    (project / SURFACE_ARTIFACT).write_text("", encoding="utf-8")
    with caplog.at_level("INFO", logger="terp.core"):
        _app()
    assert SURFACE_ARTIFACT not in _logged(caplog)


def test_in_development_an_unreadable_record_is_a_warning(
    project: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    (project / SURFACE_ARTIFACT).write_text("{", encoding="utf-8")
    with caplog.at_level("WARNING", logger="terp.core"):
        _app()
    assert f"{SURFACE_ARTIFACT} cannot be read (" in _logged(caplog)


# --------------------------------------------------------------------------- #
# what the record cannot hold refuses before anything is compared
# --------------------------------------------------------------------------- #
def test_a_route_the_record_cannot_hold_refuses(
    project: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A router included inside the module's router, and a path two routes serve.

    The record of the plain app matches both by its own lines, which is why neither is
    compared: "no difference" would be an answer about a surface that is not the one served.
    """
    _record(project)
    _deployed(monkeypatch)
    router = _router()
    nested = APIRouter()

    @nested.get("/export")
    @route_policy(Policy.public(reason="a nested export"))
    def export() -> dict:
        return {}

    router.include_router(nested, prefix="/deep")

    @router.get("/thing")
    def again() -> dict:
        return {}

    with pytest.raises(BootError) as refused:
        create_app(
            [ModuleSpec(name="probe", router=router, policy=Policy.default())],
            control_plane=ControlPlane(),
        )
    message = str(refused.value)
    assert f"cannot be compared with {SURFACE_ARTIFACT}: 2 route(s)" in message
    assert "GET /api/v1/probe/deep/export: served, but the access graph cannot place it" in message
    assert "GET /api/v1/probe/thing: served by 2 routes" in message


def test_the_record_is_the_bytes_the_check_before_release_reads(project: pathlib.Path) -> None:
    """One record for both halves: what `terp inspect access --format surface` writes."""
    _record(project)
    record = json.loads((project / SURFACE_ARTIFACT).read_text(encoding="utf-8"))
    assert record["authz_surface"] == 1
    assert check(project, "tests.architecture.test_startup_surface:_app", note_prefix="")[0] == 0
