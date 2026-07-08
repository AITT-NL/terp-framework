"""``terp openapi`` — export the app's OpenAPI document for the frontend contract.

The frontend contract's API client is *generated* from the backend OpenAPI (design
§7.1), so the two can never drift. This command writes that document straight from the
live FastAPI app — the same object ``create_app`` returns — into a JSON file the
frontend codegen consumes. It is the Python-side seam of Phase 4: no hand-rolled fetch
client and no second, hand-maintained schema (ADR 0041).
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys
from typing import Any

from fastapi import FastAPI


def _load_app(dotted: str) -> FastAPI:
    """Resolve a ``module:attribute`` reference to a FastAPI application.

    Accepts either an app instance (``app.main:app``) or a zero-argument factory that
    returns one (``app.main:build``), mirroring uvicorn's ``--factory`` convention.
    """
    module_name, _, attr = dotted.partition(":")
    if not module_name:
        raise SystemExit(f"{dotted!r} is not a valid 'module:attribute' reference")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "app")
    if isinstance(candidate, FastAPI):
        return candidate
    if callable(candidate):
        built = candidate()
        if isinstance(built, FastAPI):
            return built
    raise SystemExit(f"{dotted!r} did not resolve to a FastAPI application")


def export_openapi(
    app_ref: str = "app.main:app",
    *,
    out: str | pathlib.Path = "openapi.json",
    app_root: str | pathlib.Path = ".",
) -> pathlib.Path:
    """Write *app_ref*'s OpenAPI document to *out* as JSON; return the path.

    *app_root* is placed first on ``sys.path`` so the app package imports when ``terp``
    runs as an installed console script (where the working directory is not on the path).
    The output is sorted and indented, so a regenerated contract diffs cleanly.
    """
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    app = _load_app(app_ref)
    spec: dict[str, Any] = app.openapi()
    destination = pathlib.Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the generated artifact byte-stable across platforms, so a
    # committed, drift-checked contract does not flip to CRLF when regenerated on Windows.
    destination.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
