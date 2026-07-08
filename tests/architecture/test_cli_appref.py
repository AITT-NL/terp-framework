"""The shared CLI app-reference loader (``terp.cli._appref``).

Resolves a ``module:attribute`` reference to a FastAPI app (instance or factory) and primes
``sys.path`` — the common preamble every DB-touching subcommand (``seed``, ``user create``)
runs before it opens a session.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli._appref import load_app, push_app_root  # noqa: E402  (import after sys.path setup)

_APP = """\
from terp.core import create_app


def build():
    return create_app([])


app = build()
NOT_AN_APP = 123
"""


def _write(tmp_path: pathlib.Path, name: str) -> str:
    (tmp_path / f"{name}.py").write_text(_APP, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    sys.modules.pop(name, None)
    return name


def test_load_app_accepts_an_instance(tmp_path: pathlib.Path) -> None:
    from fastapi import FastAPI

    name = _write(tmp_path, "appref_inst")
    assert isinstance(load_app(f"{name}:app"), FastAPI)


def test_load_app_accepts_a_factory(tmp_path: pathlib.Path) -> None:
    from fastapi import FastAPI

    name = _write(tmp_path, "appref_build")
    assert isinstance(load_app(f"{name}:build"), FastAPI)


def test_load_app_rejects_an_empty_reference() -> None:
    with pytest.raises(SystemExit, match="not a valid"):
        load_app(":build")


def test_load_app_rejects_a_non_app(tmp_path: pathlib.Path) -> None:
    name = _write(tmp_path, "appref_notapp")
    with pytest.raises(SystemExit, match="did not resolve to a FastAPI"):
        load_app(f"{name}:NOT_AN_APP")


def test_push_app_root_inserts_once(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    push_app_root(root)
    assert sys.path[0] == str(root.resolve())
    # Idempotent: a second push does not duplicate the entry.
    push_app_root(root)
    assert sys.path.count(str(root.resolve())) == 1
