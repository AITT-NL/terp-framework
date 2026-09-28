"""A suite that signs tokens needs no key of its own (ADR 0163).

The development ``SECRET_KEY`` is ten bytes on purpose, and pyjwt warns on every token
signed with an HMAC key under 32 bytes, so an app's tests used to hard-code a longer key —
a literal the secret scan then flags. The shipped plugin now installs a random one for the
session while the default is in place.

Run in a subprocess against a throwaway project, as ``test_strict_isolation`` is: what is
under test is what the plugin does to *another* run's settings, from session start to the
moment the session is over.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from importlib.metadata import entry_points

_PLUGIN = "terp.core.testing"

# Same rule as the repo-root conftest: installed, the entry point loads the plugin; from
# source it has to be named, and naming it twice makes pytest refuse to start.
_NAME_THE_PLUGIN = (
    ()
    if any(ep.value == _PLUGIN for ep in entry_points(group="pytest11"))
    else ("-p", _PLUGIN)
)

_CONFTEST = '''\
"""Writes the key in force once the session is over, so the parent can read it."""

import pathlib

from terp.core.config import settings


def pytest_sessionfinish(session, exitstatus):
    pathlib.Path("key-after-session.txt").write_text(settings.SECRET_KEY, encoding="utf-8")
'''

_TEST = '''\
import pathlib
import uuid
import warnings

from terp.core import Roles
from terp.core.config import settings

from terp.capabilities.auth import create_access_token, decode_access_token


def test_a_token_signs_and_verifies_without_a_key_length_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        token = create_access_token(subject=uuid.uuid4(), role=Roles.VIEWER)
        decode_access_token(token)


def test_the_key_in_force_is_reported() -> None:
    pathlib.Path("key-during-session.txt").write_text(settings.SECRET_KEY, encoding="utf-8")
'''


def _run(root: pathlib.Path, **env: str) -> str:
    """Run the throwaway suite green, and return the key its tests signed with."""
    root.joinpath("conftest.py").write_text(_CONFTEST, encoding="utf-8")
    root.joinpath("test_signing.py").write_text(_TEST, encoding="utf-8")
    environment = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"} | env
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *_NAME_THE_PLUGIN, "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return root.joinpath("key-during-session.txt").read_text(encoding="utf-8")


def test_the_default_key_is_replaced_for_the_session_and_put_back(
    tmp_path: pathlib.Path,
) -> None:
    key = _run(tmp_path)
    assert key != "changethis"
    assert len(key) >= 32
    assert tmp_path.joinpath("key-after-session.txt").read_text(encoding="utf-8") == "changethis"


def test_a_key_the_environment_sets_is_left_alone(tmp_path: pathlib.Path) -> None:
    """A deliberately configured key is the suite's own decision."""
    chosen = "a-key-this-suite-chose-for-itself-0123456789"
    assert _run(tmp_path, SECRET_KEY=chosen) == chosen
