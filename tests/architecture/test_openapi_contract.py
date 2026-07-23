"""Phase 4: the committed OpenAPI specs must not drift from the backend.

Two generated specs are committed so the frontend has stable, reviewable inputs, and this gate
fails closed if either falls behind the live backend — the same "committed generated artifact +
no-drift test" shape as the vendored core mirror (ADR 0034). The checks are semantic (parsed JSON),
robust to formatting / line endings, and report exactly which routes / schemas drifted:

- ``packages/frontend/contract/openapi.json`` is the ``@terpjs/contract`` baked schema: the
  BASE-PROFILE surface every Terp app has (auth, ``/me``, users, access, audit, ...), exported from
  ``app.main:build_base_profile`` — NOT this example's domain modules. react-core and a generated
  repo's default client are typed from it.
- ``apps/example/openapi.json`` is the example app's OWN full spec (``app.main:app``), the source
  its frontend's ``openapi-typescript`` codegen consumes — dogfooding exactly how a generated repo
  types calls to its own endpoints (ADR 0041).

Regenerate after a backend API change with::

    terp openapi --app app.main:build_base_profile --out packages/frontend/contract/openapi.json --app-root apps/example
    terp openapi --app app.main:app --out apps/example/openapi.json --app-root apps/example
"""

from __future__ import annotations

import json
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
_EXAMPLE = _REPO_ROOT / "apps" / "example"
_CONTRACT = _REPO_ROOT / "packages" / "frontend" / "contract" / "openapi.json"
_EXAMPLE_SPEC = _EXAMPLE / "openapi.json"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import export_openapi  # noqa: E402


def _regenerate(app_ref: str, out: pathlib.Path) -> dict:
    """Export *app_ref*'s live OpenAPI to *out* and return the parsed spec."""
    return json.loads(
        export_openapi(app_ref, out=out, app_root=_EXAMPLE).read_text(encoding="utf-8")
    )


def _assert_no_drift(committed: dict, regenerated: dict, *, artifact: str, regen: str) -> None:
    """Fail with a route/schema diff if the *committed* spec is not the *regenerated* one."""
    committed_paths = set(committed.get("paths", {}))
    live_paths = set(regenerated.get("paths", {}))
    committed_schemas = set(committed.get("components", {}).get("schemas", {}))
    live_schemas = set(regenerated.get("components", {}).get("schemas", {}))
    assert committed == regenerated, (
        f"the committed {artifact} is stale; regenerate with `{regen}`:\n"
        f"  paths only in committed: {sorted(committed_paths - live_paths)}\n"
        f"  paths only in app:       {sorted(live_paths - committed_paths)}\n"
        f"  schemas only in committed: {sorted(committed_schemas - live_schemas)}\n"
        f"  schemas only in app:       {sorted(live_schemas - committed_schemas)}"
    )


def test_openapi_contract_present() -> None:
    """Fail closed if the committed base-profile contract is missing/empty (guards false greens)."""
    assert _CONTRACT.is_file(), f"frontend OpenAPI contract missing: {_CONTRACT}"
    spec = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    assert spec.get("openapi", "").startswith("3.")
    assert spec.get("paths") and spec.get("components", {}).get("schemas")


def test_openapi_contract_is_base_profile_only(tmp_path: pathlib.Path) -> None:
    """The @terpjs/contract spec must equal the base-profile app — framework surface, no domain modules."""
    committed = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    regenerated = _regenerate("app.main:build_base_profile", tmp_path / "openapi.json")
    # The example's own domain modules must NOT leak into the bundled contract.
    domain = ("/api/v1/notes", "/api/v1/tasks", "/api/v1/projects", "/api/v1/journals")
    assert not [route for route in regenerated.get("paths", {}) if route.startswith(domain)]
    _assert_no_drift(
        committed,
        regenerated,
        artifact="frontend OpenAPI contract (packages/frontend/contract/openapi.json)",
        regen=(
            "terp openapi --app app.main:build_base_profile "
            "--out packages/frontend/contract/openapi.json --app-root apps/example"
        ),
    )


def test_example_openapi_present() -> None:
    """Fail closed if the example's own committed spec (its codegen source) is missing/empty."""
    assert _EXAMPLE_SPEC.is_file(), f"example OpenAPI spec missing: {_EXAMPLE_SPEC}"
    spec = json.loads(_EXAMPLE_SPEC.read_text(encoding="utf-8"))
    assert spec.get("openapi", "").startswith("3.")
    assert spec.get("paths") and spec.get("components", {}).get("schemas")


def test_example_openapi_matches_the_live_app(tmp_path: pathlib.Path) -> None:
    """The example's committed spec must equal its live app (app.main:app) — its frontend codegen source."""
    committed = json.loads(_EXAMPLE_SPEC.read_text(encoding="utf-8"))
    regenerated = _regenerate("app.main:app", tmp_path / "openapi.json")
    # The example spec DOES include the domain modules (that is what its frontend types calls to).
    assert "/api/v1/notes/" in regenerated.get("paths", {})
    _assert_no_drift(
        committed,
        regenerated,
        artifact="example OpenAPI spec (apps/example/openapi.json)",
        regen="terp openapi --app app.main:app --out apps/example/openapi.json --app-root apps/example",
    )
