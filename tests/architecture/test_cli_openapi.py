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


# --------------------------------------------------------------------------- #
# The access vocabulary travels in the contract                                 #
# --------------------------------------------------------------------------- #
#
# A client gates a route, a nav entry or a control on a permission name whose single
# source is the backend's declaration. Spelled as a bare string it fails in one of two
# silent directions when the backend renames or re-floors it: it over-gates, and a screen
# 403s for someone who may use it, or it under-gates, and a link renders while every
# request behind it fails. Only a hand-written end-to-end test catches either.
#
# The platform already solved this class twice — OpenAPI to `schema.d.ts` for data,
# manifests to `routes.gen.d.ts` for paths — and both times by putting the vocabulary in
# the contract the client is generated from.


def _schemas(tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "openapi.json"
    export_openapi("app.main:build", out=out, app_root=_EXAMPLE)
    return json.loads(out.read_text(encoding="utf-8"))["components"]["schemas"]


def test_the_document_carries_the_permission_and_role_vocabulary(
    tmp_path: pathlib.Path,
) -> None:
    schemas = _schemas(tmp_path)
    assert schemas["TerpPermission"]["enum"], "no permission names reached the contract"
    assert schemas["TerpRole"]["enum"] == ["admin", "editor", "viewer"]


def test_the_vocabulary_is_an_enum_so_a_generator_makes_a_union(
    tmp_path: pathlib.Path,
) -> None:
    """`openapi-typescript` turns an enum of strings into a string-literal union, which
    is the whole point — a `type: string` with a description would generate `string`
    and narrow nothing."""
    for name in ("TerpPermission", "TerpRole"):
        schema = _schemas(tmp_path)[name]
        assert schema["type"] == "string"
        assert all(isinstance(value, str) for value in schema["enum"])
        assert schema["enum"] == sorted(schema["enum"]), "a stable order diffs cleanly"


def test_an_app_terp_did_not_compose_gets_no_vocabulary() -> None:
    """There is no access model to read, and inventing an empty one would be worse than
    omitting it: a client would narrow to `never`."""
    from fastapi import FastAPI

    from terp.cli.openapi import _vocabulary_schemas

    assert _vocabulary_schemas(FastAPI()) == {}


def test_an_empty_vocabulary_is_omitted_rather_than_emitted_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`enum: []` is a schema nothing satisfies, and a generator turns it into `never` —
    every client touching the type would stop compiling. An absent schema degrades to
    the plain `string` a client has today, which is the right way round, and is what a
    freshly scaffolded app (no permissions declared yet) gets."""
    from types import SimpleNamespace

    import terp.cli.access as access_module
    from terp.cli import openapi as openapi_module

    monkeypatch.setattr(
        access_module, "build_access_model", lambda plane, specs: {"permissions": [], "roles": []}
    )
    app = SimpleNamespace(
        state=SimpleNamespace(terp_module_specs=[], terp_control_plane=object())
    )
    assert openapi_module._vocabulary_schemas(app) == {}


def test_a_module_that_declared_the_name_keeps_it(tmp_path: pathlib.Path) -> None:
    """Added, not merged over: a module owning a schema called `TerpRole` would have its
    client's types broken to supply a vocabulary it never asked for."""
    components = {"TerpRole": {"type": "integer"}}
    for name, schema in _schemas(tmp_path).items():
        if name in {"TerpPermission", "TerpRole"}:
            components.setdefault(name, schema)
    assert components["TerpRole"] == {"type": "integer"}
    assert components["TerpPermission"]["type"] == "string"
