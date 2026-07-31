"""The reporting half of the shipped isolation plugin (:mod:`terp.core.testing`).

Strict isolation resets **before** fixtures run, so an autouse fixture that installs a
runtime for a whole package is structurally invisible to it: every test is handed a bus
it never asked for, the reset happens first, and the strict run stays green. That is the
real shape of the failure an app hit — a blanket ``configure_events`` in ``conftest.py``
— and no amount of tightening strict mode can catch it, because autouse installers are
legitimate.

``--terp-report-runtime-installs`` answers the question strict mode cannot: which test
installed which seam. The answer's *shape* is the finding — one or two ids under a seam
is a test installing what it needs; every id under a seam is a fixture doing it for them.

A subprocess rather than the ``pytester`` fixture, for the same reason as
``test_strict_isolation``: the thing under test is what the plugin does across another
run's setup, teardown and terminal summary.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from importlib.metadata import entry_points

import pytest

from terp.core import testing as terp_testing

_PLUGIN = "terp.core.testing"

_NAME_THE_PLUGIN = (
    ()
    if any(ep.value == _PLUGIN for ep in entry_points(group="pytest11"))
    else ("-p", _PLUGIN)
)

_CONFTEST = '''\
"""One autouse installer, exactly as an app writes it — invisible to strict mode."""

import pytest

from terp.core import BaseSchema
from terp.core.events import EventCatalog, EventDefinition, configure_events


class DemoPayload(BaseSchema):
    id: str


ORDERED = EventDefinition(name="demo.ordered", payload_schema=DemoPayload)


@pytest.fixture(autouse=True)
def configure_the_bus_for_every_test() -> None:
    configure_events(EventCatalog([ORDERED]))
'''

_TESTS = '''\
from conftest import ORDERED

from terp.core.events import emit


def test_emits() -> None:
    emit(None, event=ORDERED, payload={"id": "1"})


def test_does_not_emit_but_is_handed_the_bus_anyway() -> None:
    assert True is True
'''


def _write_project(root: pathlib.Path) -> None:
    root.joinpath("conftest.py").write_text(_CONFTEST, encoding="utf-8")
    root.joinpath("test_carried.py").write_text(_TESTS, encoding="utf-8")
    root.joinpath("pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _run(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *_NAME_THE_PLUGIN, "-q", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_report_names_every_test_an_autouse_installer_carries(
    tmp_path: pathlib.Path,
) -> None:
    """The whole point: a seam under *every* test id is a fixture, not a test."""
    _write_project(tmp_path)
    result = _run(tmp_path, "--terp-report-runtime-installs")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "terp runtime installs" in output, output
    assert "events: installed by 2 test(s)" in output, output
    assert "test_carried.py::test_emits" in output, output
    assert "test_carried.py::test_does_not_emit_but_is_handed_the_bus_anyway" in output, output


def test_a_strict_run_reports_the_install_and_not_its_own_reset(
    tmp_path: pathlib.Path,
) -> None:
    """Strict mode stays green here — which is the finding, and the report says why."""
    _write_project(tmp_path)
    result = _run(tmp_path, "--terp-strict-isolation", "--terp-report-runtime-installs")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    # Compared against what the test STARTED from (the baseline), so the reset the
    # fixture just performed is not itself reported as an install.
    assert "events: installed by 2 test(s)" in output, output


def test_a_suite_that_installs_nothing_says_so(tmp_path: pathlib.Path) -> None:
    """An empty report is a real answer, so it is printed rather than left blank."""
    tmp_path.joinpath("pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    tmp_path.joinpath("test_quiet.py").write_text(
        "def test_touches_no_runtime() -> None:\n    assert True is True\n",
        encoding="utf-8",
    )
    result = _run(tmp_path, "--terp-report-runtime-installs")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "No test installed a Terp runtime seam." in output, output


def test_the_report_is_silent_unless_asked_for(tmp_path: pathlib.Path) -> None:
    """It is a diagnostic, not a thing every run pays for in output."""
    _write_project(tmp_path)
    result = _run(tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "terp runtime installs" not in output, output


class _Reporter:
    """The two ``TerminalReporter`` methods the summary hook uses, and its config."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.lines: list[str] = []

    def write_sep(self, _sep: str, title: str) -> None:
        self.lines.append(title)

    def write_line(self, line: str) -> None:
        self.lines.append(line)


def _summary(config: pytest.Config) -> list[str]:
    reporter = _Reporter(config)
    terp_testing.pytest_terminal_summary(reporter)  # type: ignore[arg-type]
    return reporter.lines


def test_the_summary_prints_nothing_when_no_report_was_collected(
    pytestconfig: pytest.Config,
) -> None:
    """The in-process half of the silence: no stash entry, no section at all."""
    assert _summary(pytestconfig) == []


def test_the_summary_groups_the_ids_under_their_seam(pytestconfig: pytest.Config) -> None:
    """Rendered in the shape a reader has to judge: seam, count, then the ids."""
    pytestconfig.stash[terp_testing._INSTALLS_KEY] = {
        "events": ["t.py::a", "t.py::b"],
        "audit": ["t.py::a"],
    }
    try:
        lines = _summary(pytestconfig)
    finally:
        del pytestconfig.stash[terp_testing._INSTALLS_KEY]
    assert lines == [
        "terp runtime installs",
        "audit: installed by 1 test(s)",
        "  t.py::a",
        "events: installed by 2 test(s)",
        "  t.py::a",
        "  t.py::b",
    ]


def test_an_empty_collection_still_says_so(pytestconfig: pytest.Config) -> None:
    """"Nothing installed anything" is an answer; a blank section is not."""
    pytestconfig.stash[terp_testing._INSTALLS_KEY] = {}
    try:
        lines = _summary(pytestconfig)
    finally:
        del pytestconfig.stash[terp_testing._INSTALLS_KEY]
    assert lines == ["terp runtime installs", "No test installed a Terp runtime seam."]


def test_a_seam_that_was_not_there_at_the_start_counts_as_installed(
    pytestconfig: pytest.Config,
) -> None:
    """A newly *registered* seam is an install too — absent is not "unchanged"."""
    pytestconfig.option.terp_report_runtime_installs = True
    try:
        terp_testing._record_installs(pytestconfig, "t.py::new_seam", {})
        installs = pytestconfig.stash[terp_testing._INSTALLS_KEY]
        assert installs, "every registered seam should be reported against an empty start"
        assert all(ids == ["t.py::new_seam"] for ids in installs.values())
    finally:
        pytestconfig.option.terp_report_runtime_installs = False
        del pytestconfig.stash[terp_testing._INSTALLS_KEY]


def test_nothing_is_recorded_when_the_flag_is_off(pytestconfig: pytest.Config) -> None:
    """The default path every other test in this suite takes: no stash, no cost."""
    terp_testing._record_installs(pytestconfig, "t.py::whatever", {})
    assert terp_testing._INSTALLS_KEY not in pytestconfig.stash
