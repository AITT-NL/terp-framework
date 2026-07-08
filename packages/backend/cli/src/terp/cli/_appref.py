"""Shared CLI helper: resolve a ``module:attribute`` app reference and prime ``sys.path``.

Several ``terp`` subcommands (``seed``, ``user create``, …) build the app before they touch
the database, because building it runs ``create_app`` — which configures the engine, the
durable audit sink, and the job / event catalogs. Centralising that resolution keeps every
command on one loader (mirrors the ``terp openapi`` / ``terp jobs`` loaders).
"""

from __future__ import annotations

import importlib
import pathlib
import sys

from fastapi import FastAPI


def push_app_root(app_root: str | pathlib.Path) -> None:
    """Place *app_root* first on ``sys.path`` so the app package imports as a console script."""
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def load_app(dotted: str) -> FastAPI:
    """Resolve ``module:attribute`` to a FastAPI app (an instance or a zero-arg factory).

    Building the app runs ``create_app``, so the engine, the durable audit sink, and the
    catalogs are configured before the command opens a session. A bad reference fails closed
    with a clean :class:`SystemExit`.
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
