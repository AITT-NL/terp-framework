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


#: The two vocabularies a client re-states by hand today, and what each one is for.
#:
#: A frontend gates a route, a nav entry or a control on a permission name, and that
#: name's single source is the backend's declaration. Restating it as a bare string
#: means a renamed or re-floored permission fails in one of two silent directions:
#: it over-gates, and a screen 403s for someone who may use it, or it under-gates, and
#: a link renders while every request behind it fails. Only a hand-written end-to-end
#: test catches either.
#:
#: The platform already solved this class twice -- OpenAPI to `schema.d.ts` for data,
#: manifests to `routes.gen.d.ts` for paths -- and both times by putting the vocabulary
#: in the contract the client is generated from. This is the third.
#:
#: Emitted as an `enum` of names rather than as the structured records `terp inspect
#: access --format json` returns, because an enum is what a generator turns into a
#: string-literal union. The structure stays where it already is; this is the
#: type-level half.
_VOCABULARY = (
    (
        "TerpPermission",
        "permissions",
        "Every permission name this app declares. Gate a client control on one of "
        "these rather than on a string literal, so a rename stops type-checking "
        "instead of silently over- or under-gating.",
    ),
    (
        "TerpRole",
        "roles",
        "Every role name this app's modules declare, for the same reason.",
    ),
)


def _vocabulary_schemas(app: FastAPI) -> dict[str, dict[str, Any]]:
    """``TerpPermission`` / ``TerpRole`` schemas for a composed app.

    Empty for an app ``create_app`` did not compose (there is no access model to read)
    and for a vocabulary that is empty -- an ``enum: []`` is a schema nothing can
    satisfy, and a generator turns it into ``never``, which would make every client
    that touches the type stop compiling. An absent schema degrades to the plain
    ``string`` a client has today, which is the right way round.
    """
    specs = getattr(app.state, "terp_module_specs", None)
    plane = getattr(app.state, "terp_control_plane", None)
    if specs is None or plane is None:
        return {}
    from terp.cli.access import build_access_model

    model = build_access_model(plane, specs)
    schemas: dict[str, dict[str, Any]] = {}
    for schema_name, key, description in _VOCABULARY:
        names = sorted(
            entry["name"]
            for entry in model.get(key, ())
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        )
        if names:
            schemas[schema_name] = {
                "type": "string",
                "enum": names,
                "title": schema_name,
                "description": description,
            }
    return schemas


def openapi_document(app: FastAPI) -> dict[str, Any]:
    """The document :func:`export_openapi` writes for *app*, as parsed JSON.

    One function for the writer and for the ``api-contract`` check (ADR 0194), so the check
    compares the committed file with exactly what regenerating it would write. The JSON
    round trip is part of that: what a check compares is what a file can hold.
    """
    spec: dict[str, Any] = app.openapi()
    # Added rather than merged over: a module that has declared a schema under one of
    # these names owns it, and silently replacing it would break that client's types to
    # supply a vocabulary it did not ask for.
    components = spec.setdefault("components", {}).setdefault("schemas", {})
    for name, schema in _vocabulary_schemas(app).items():
        components.setdefault(name, schema)
    document: dict[str, Any] = json.loads(json.dumps(spec))
    return document


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
    destination = pathlib.Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the generated artifact byte-stable across platforms, so a
    # committed, drift-checked contract does not flip to CRLF when regenerated on Windows.
    destination.write_text(
        json.dumps(openapi_document(app), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def _readable_document(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def run_openapi_command(
    app_ref: str = "app.main:app",
    *,
    out: str | pathlib.Path = "openapi.json",
    app_root: str | pathlib.Path = ".",
) -> str:
    """``terp openapi``: write the document, and name what changed when it overwrites one.

    Regenerating is how a change to a committed contract is accepted (ADR 0194), so the
    person who runs it is shown what they are accepting, breaking lines first, before the
    line that says what was written. A file that was absent or unreadable has nothing to
    compare with, and a document that did not change prints only what was written.
    """
    from terp.cli.api_contract import diff_contract, render_changes

    previous = _readable_document(pathlib.Path(out))
    written = export_openapi(app_ref, out=out, app_root=app_root)
    lines = [f"wrote {written}"]
    current = _readable_document(written)
    if previous is not None and current is not None:
        changes = diff_contract(previous, current)
        if changes:
            breaking = sum(1 for change in changes if change.breaking)
            lines.insert(
                0,
                f"the contract changed in {len(changes)} way(s), {breaking} of them "
                f"breaking:\n{render_changes(changes)}",
            )
    return "\n".join(lines)
