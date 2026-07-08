"""Phase 4 frontend contract: ``terp openapi`` — the OpenAPI export seam.

The frontend contract's API client is generated from this document (design §7.1 / ADR
0041), so these tests prove the command writes the *live* app's spec, accepts both an app
instance and a factory, fails closed on a bad reference, and — locking the ADR-0020
property at the contract boundary — that no ``*Read`` response schema leaks a password.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
_EXAMPLE = _REPO_ROOT / "apps" / "example"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import export_openapi, main  # noqa: E402


def _read_spec(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_openapi_writes_the_live_spec(tmp_path: pathlib.Path) -> None:
    out = export_openapi("app.main:app", out=tmp_path / "contract" / "openapi.json", app_root=_EXAMPLE)
    spec = _read_spec(out)
    assert spec["openapi"].startswith("3.")
    # The live routes are present, so the generated client covers the real surface.
    assert "/api/v1/notes/" in spec["paths"]
    assert spec["components"]["schemas"]  # response/request DTOs are emitted


def test_export_openapi_does_not_leak_a_password(tmp_path: pathlib.Path) -> None:
    # ADR 0020 (a response_model is never a table model) holds at the contract boundary:
    # no generated *Read schema can carry a password / hash for the frontend to receive.
    spec = _read_spec(export_openapi("app.main:app", out=tmp_path / "openapi.json", app_root=_EXAMPLE))
    leaks = [
        name
        for name, schema in spec["components"]["schemas"].items()
        if "Read" in name and "password" in json.dumps(schema).lower()
    ]
    assert leaks == []


def test_export_openapi_accepts_a_factory(tmp_path: pathlib.Path) -> None:
    # `app.main:build` is a zero-arg factory (uvicorn `--factory` style), not an instance.
    out = export_openapi("app.main:build", out=tmp_path / "openapi.json", app_root=_EXAMPLE)
    assert _read_spec(out)["openapi"].startswith("3.")


def test_export_openapi_rejects_a_non_app(tmp_path: pathlib.Path) -> None:
    # `settings` resolves but is neither a FastAPI app nor a factory for one.
    with pytest.raises(SystemExit):
        export_openapi("app.main:settings", out=tmp_path / "openapi.json", app_root=_EXAMPLE)


def test_export_openapi_rejects_a_bad_reference(tmp_path: pathlib.Path) -> None:
    # A fresh app_root (not yet on sys.path) also exercises the path insertion.
    with pytest.raises(SystemExit):
        export_openapi(":app", out=tmp_path / "openapi.json", app_root=tmp_path)


def test_cli_openapi_writes_file(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "openapi.json"
    main(["openapi", "--app", "app.main:app", "--out", str(out), "--app-root", str(_EXAMPLE)])
    assert "wrote" in capsys.readouterr().out
    assert _read_spec(out)["openapi"].startswith("3.")
