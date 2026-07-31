"""The strict half of the shipped isolation plugin (:mod:`terp.core.testing`).

Snapshot-and-restore is faithful, and that is exactly its blind spot: a runtime
installed *before* the first test — a stray import at collection time, a module-scope
``create_app()`` — is part of the snapshot, so it is put back before every test and
covers every test equally. The suite is green together and red alone, and the fixture
cannot see it, because nothing leaked.

These tests pin the difference by running a real pytest process against a throwaway
project whose ``conftest.py`` installs an event runtime at import time and whose test
asserts on it without installing anything itself. That is the app's failure shape,
reproduced end to end: it must pass by default (an existing suite pays nothing) and
fail under ``--terp-strict-isolation`` (the ambient runtime stops being cover).

A subprocess rather than the ``pytester`` fixture: the thing under test is what the
plugin does at *collection and setup* of another run, so it needs its own process.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

_AMBIENT_CONFTEST = '''\
"""Installs an event runtime at import time — the leak a restore reproduces."""

from terp.core import BaseSchema
from terp.core.events import EventCatalog, EventDefinition, configure_events


class DemoPayload(BaseSchema):
    id: str


ORDERED = EventDefinition(name="demo.ordered", payload_schema=DemoPayload)
configure_events(EventCatalog([ORDERED]))
'''

_AMBIENT_TEST = '''\
from conftest import ORDERED

from terp.core.events import emit


def test_reads_a_runtime_it_never_installed() -> None:
    """Passes only because conftest.py installed the catalog at import time."""
    emit(None, event=ORDERED, payload={"id": "1"})
'''


def _write_project(root: pathlib.Path, *, strict: bool) -> None:
    root.joinpath("conftest.py").write_text(_AMBIENT_CONFTEST, encoding="utf-8")
    root.joinpath("test_ambient.py").write_text(_AMBIENT_TEST, encoding="utf-8")
    strict_line = "terp_strict_isolation = true\n" if strict else ""
    root.joinpath("pytest.ini").write_text(
        textwrap.dedent(f"""\
            [pytest]
            {strict_line}"""),
        encoding="utf-8",
    )


def _run(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "terp.core.testing", "-q", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_failed_on_the_missing_catalog(result: subprocess.CompletedProcess[str]) -> None:
    """Fail *because the runtime is gone*, not on an import slip in the fixture project."""
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "is not registered in the EventCatalog" in output, output


def test_an_ambient_runtime_still_covers_a_test_by_default(tmp_path: pathlib.Path) -> None:
    """Default isolation costs an existing suite nothing — including this bad one."""
    _write_project(tmp_path, strict=False)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_strict_isolation_fails_the_test_that_installed_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """The same suite, told to start every test from the platform baseline."""
    _write_project(tmp_path, strict=False)
    _assert_failed_on_the_missing_catalog(_run(tmp_path, "--terp-strict-isolation"))


def test_strict_isolation_reads_the_ini_option_too(tmp_path: pathlib.Path) -> None:
    """A project adopts it once in pyproject/pytest.ini, not on every invocation."""
    _write_project(tmp_path, strict=True)
    _assert_failed_on_the_missing_catalog(_run(tmp_path))
